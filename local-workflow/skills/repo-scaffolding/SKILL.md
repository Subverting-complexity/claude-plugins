---
name: repo-scaffolding
description: "Scaffold a brand-new project from scratch: discovery, architecture, and decomposition into epics and user stories with acceptance criteria. Use to plan a greenfield project, set up a new repo, or turn a product idea into buildable work. Do NOT use for adding features to an existing codebase (use feature-discovery), stress-testing a plan without producing stories (use grill), or implementing code (use execute)."
depends-on:
  - grill
  - code-architect
---
<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->

# Repo Scaffolding

Plan a new project and decompose it into epics and user stories. The interview that gets there is the `grill` skill's; this skill decides what the interview must cover and what gets built from its answers.

## Output standard

Everything a person reads — plans, questions, findings, summaries, and anything posted or committed — follows `skills/_shared/wording-standard.md` for how it reads, `skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `skills/_shared/banned-patterns.md` for what must never appear. Every reply, not only the last one.

## Skills Used

Read each skill's SKILL.md when you reach the phase that needs it.

- **grill** (`/local-workflow:grill`) — The interview: how questions are asked, paced and closed, and what happens when nobody is present to answer.
- **code-architect** (`/local-workflow:code-architect`) — Architecture design and validation.

## Scope Detection

Determine the project scope before starting. It decides which coverage topics apply.

| Tier | Signal | Coverage |
|------|--------|----------|
| **Small** | Simple tool, script, single-purpose utility, CLI app | Vision and scope, tech stack. |
| **Medium** | Multi-module app, API + frontend, 2-4 major concerns | Adds journeys, data, API, architecture, dependencies, DevOps. |
| **Large** | Platform, multi-service system, 5+ sprints of work | Every topic. |

After the research, state the tier and the topics it brings in, and continue: "This looks like a medium-scope project, so the interview will cover scope, data model, API surface and architecture." Do not stop to ask for confirmation. The user can correct the tier at any point, and a correction changes the coverage list.

---

## Phase 1: Research

Gather what you can from whatever the user has provided before the interview starts.

1. Read any existing documentation, specs, reference materials, wireframes, or design docs the user has shared.
2. If a repo already exists (even empty with just a README or config), read what's there.
3. If similar projects or reference codebases are mentioned, review them.
4. Search for relevant patterns, frameworks, or prior art if it helps narrow the interview.

Present a brief summary of what you found, then state the scope tier as above.

---

## Phase 2: Interview

Read `skills/grill/SKILL.md` and run it with the project as the plan. Its posture, question wording, `AskUserQuestion` rules, pacing and no-person-present rule govern the whole interview; this skill adds none of its own. Every resolved question informs the stories, and every deferred one becomes an open item in Phase 5.

### Coverage topics

Hand the grill the topics for the tier. They are not a script to read out: the grill asks about them in its own order and batches, and uses this list at the end as a check that nothing was missed. A topic the provided documentation already answers counts as covered.

1. **Vision and scope** (all tiers): what is being built and the problem it solves, who the users are, what is out of scope for v1, what "done" means for the first usable version.
2. **User journeys** (medium + large): the happy path for the primary user, secondary users and their flows, failure modes and error states.
3. **Data model** (medium + large): core entities and relationships, storage strategy (database, hosting, migrations), data lifecycle (creation, change, deletion, archival).
4. **API surface** (medium + large): what the product exposes, service-to-service APIs if there are several services, the auth and permission model, third-party integrations.
5. **Tech stack** (all tiers): language, framework and runtime, infrastructure and hosting, CI/CD, key libraries or tools.
6. **Architecture** (medium + large): monolith or services, monorepo or several repos, patterns and trade-offs, constraints (budget, timeline, team size, compliance).
7. **Dependencies and ordering** (medium + large): what must exist before other things can be built, external dependencies (APIs, services, accounts, licences), build order for epics.
8. **Testing strategy** (large, or when raised): testing approach, critical paths needing integration tests, test infrastructure (databases, mocks, fixtures).
9. **DevOps and deployment** (medium + large): environments, deployment targets, monitoring and observability.

When the grill closes with every applicable topic covered, go straight to Phase 3.

---

## Phase 3: Architecture

Use the **code-architect** skill to:
1. Select and justify architecture style
2. Define boundaries and layers
3. Identify constraints and trade-offs

For small-scope work, keep this lightweight: a brief note on the chosen pattern and why. For large-scope, produce full architecture documentation.

---

## Phase 4: Decomposition

Break the work into epics and stories.

### Epic structure

Each epic represents a logical phase of work. For each:
- Title (short, capability-focused)
- Goal (2-3 sentences)
- Dependencies on other epics
- Suggested ordering

For small-scope work, there may be only one epic or even just stories with no epic wrapper. Don't force structure that doesn't fit.

### Story structure

Use the story template from `references/story-template.md`. It is short on purpose: a Summary, the changes, and acceptance criteria, plus only the sections that carry information the implementer would otherwise have to guess. Where the plugin provides a `writing-github-issues` skill (github-workflow does), read it before writing stories that become GitHub issues, and follow it for the title as well as the body.

### Story sizing

- One session of work max. If bigger, split it.
- One concern per story (one module, one screen, one API surface).
- Technical Notes over 10 lines means the story is too big.
- Dependencies must be explicit and acyclic.

### Cross-referencing

After decomposition, verify:
- Every interview question is covered by at least one story
- No gaps in the user journey
- Dependencies are acyclic
- Ordering respects dependency chain
- Foundation stories (project setup, CI/CD, base architecture) come first

---

## Phase 5: Review

Present the plan before finalising:
1. Epic summary table (ordering, dependencies, story count)
2. Story list with one-line summaries grouped by epic
3. Dependency graph (text or visual)
4. Coverage check against interview findings
5. Open issues or deferred items

Use `AskUserQuestion`:

- "Approve (Recommended)"
- "I have changes"
- "Redo a section"

Iterate until confirmed.

---

## Output

The final deliverable is epics and stories with acceptance criteria and dependency ordering, presented in the conversation. The user can then create issues, board items, or tickets in their project management tool of choice. Do **not** write specification documents to the filesystem — the conversation and the resulting GitHub issues are the record.
