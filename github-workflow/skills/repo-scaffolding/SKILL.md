---
name: repo-scaffolding
description: "Scaffold a brand-new project from scratch: discovery, architecture, and decomposition into epics and user stories with acceptance criteria. Use to plan a greenfield project, set up a new repo, or turn a product idea into buildable work. Do NOT use for adding features to an existing codebase (use feature-discovery) or implementing code (use execute)."
depends-on:
  - code-architect
---
<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->

# Repo Scaffolding

Plan and decompose a new project into epics and user stories. Get to the core of the design as fast as possible. The interview should be relentless: probe every vague answer, challenge weak reasoning, surface conflicts between answers, and don't move on until each question has a concrete answer or a conscious deferral with a stated reason.

## Plain-English output

Everything you write for a person to read (interview questions, `AskUserQuestion` options, epics, and stories) follows `_shared/wording-standard.md` and avoids `_shared/banned-patterns.md`. Assume a technically capable reader who is not involved in this codebase. Explain what a component or pattern is before you rely on its name, stay high-level and concise, and never let a string of identifiers replace a plain explanation. Reread anything you send and strip staccato fragments and banned patterns first.

The **shape** of what you report follows
`skills/user-facing-communication/SKILL.md`: lead with the outcome and
the current state, put anything outstanding, blocked or assumed where it
cannot be missed, name every work item as well as numbering it, and leave
out the investigation history. It applies to every reply you write, not
only the last one.

## Skills Used

Read each skill's SKILL.md when you reach the phase that needs it.

- **code-architect** (`/github-workflow:code-architect`) — Architecture design and validation.

## Scope Detection

Determine the project scope before starting. This drives interview depth.

| Tier | Signal | Interview depth |
|------|--------|----------------|
| **Small** | Simple tool, script, single-purpose utility, CLI app | 5-8 questions. Scope, stack, core stories. |
| **Medium** | Multi-module app, API + frontend, 2-4 major concerns | 10-18 questions. Scope, journeys, data, API, architecture, dependencies. |
| **Large** | Platform, multi-service system, 5+ sprints of work | Full interview. All sections. |

State the tier after initial research: "This looks like a medium-scope project, so I'll focus on scope, data model, API surface, and architecture." The user can override.

---

## Phase 1: Research

Before asking the user anything, gather what you can from whatever they've provided. The more you learn here, the fewer questions you need to ask.

1. Read any existing documentation, specs, reference materials, wireframes, or design docs the user has shared.
2. If a repo already exists (even empty with just a README or config), read what's there.
3. If similar projects or reference codebases are mentioned, review them.
4. Search for relevant patterns, frameworks, or prior art if it helps narrow the interview.

### Research output

Present a brief summary of what you found, then state the scope tier
and which interview sections you plan to cover. Use `AskUserQuestion`
to confirm:

- "Agree with scope (Recommended)" — proceed with the detected tier
- "This is bigger than that" — bump up a tier
- "This is smaller" — bump down a tier

---

## Phase 2: Interview

### Interview posture

Be relentless. The goal is shared understanding with every open question resolved. Don't accept hand-waving. If the user gives a surface-level answer, dig deeper. If they say "probably" or "it depends", that's your cue to probe until the answer is concrete or the user explicitly defers (with a reason). Every resolved question informs the stories. Every deferred question becomes a noted open issue.

### Interview mechanics

- **Lead with recommendations.** For every question, state what you'd recommend and why before asking. Don't just interrogate. Give your best answer, then ask if the user agrees or wants to change it.
- **Batch related questions.** Group questions that belong to the same topic into a single turn. Don't artificially slow the interview down.
- **Push back on vague answers.** "It depends", "probably X", "we'll figure it out later" are not answers. Probe until concrete or explicitly deferred.
- **Flag conflicts.** If a later answer contradicts an earlier one, surface it immediately. Don't silently accept the contradiction.
- **Defer consciously.** If something genuinely can't be decided yet, note it as an open issue with a stated reason and move on. Never silently skip.
- **Track context.** Maintain a running internal record of resolved questions and deferrals as you go. This ensures nothing falls through the cracks during decomposition.

### Using AskUserQuestion

Use the `AskUserQuestion` tool for any question with a bounded answer
set: binary choices, picking from discovered patterns, confirming
recommendations, scope in/out decisions, phase-gate confirmations.

- 2-4 options per question, short labels.
- Your recommended answer should be the first option with
  "(Recommended)" appended to the label.
- Batch up to 4 related questions in a single `AskUserQuestion` call.
- The user can always select "Other" to type a custom answer. If you
  find yourself wanting to add an "Other" option manually, just ask
  in plain text instead.

### Interview sections

**Only cover sections relevant to the scope tier.** Skip questions already answered by provided documentation.

#### 1. Vision and scope (all tiers)
- What is being built? What problem does it solve?
- Who are the users?
- What's explicitly out of scope for v1?
- What does "done" look like for the first usable version?

#### 2. User journeys (medium + large)
- Happy path end-to-end for primary user type
- Secondary user types and their flows
- Critical failure modes and error states

#### 3. Data model (medium + large)
- Core entities and relationships
- Storage strategy (DB type, hosting, migrations)
- Data lifecycle (creation, mutation, deletion, archival)

#### 4. API surface (medium + large)
- External APIs (what the product exposes)
- Internal APIs (service-to-service if multi-service)
- Auth/permission model
- Third-party integrations

#### 5. Tech stack (all tiers)
- Language, framework, runtime
- Infrastructure and hosting
- CI/CD approach
- Key libraries or tools

#### 6. Architecture (medium + large)
- Monolith vs services, monorepo vs multi-repo
- Patterns and trade-offs
- Constraints (budget, timeline, team size, compliance)

#### 7. Dependencies and ordering (medium + large)
- What needs to exist before other things can be built?
- External dependencies (APIs, services, accounts, licenses)
- Build order for epics

#### 8. Testing strategy (large, or when raised)
- Testing philosophy (TDD, integration-first, etc.)
- Critical paths needing integration tests
- Infrastructure for testing (test DBs, mocks, fixtures)

#### 9. DevOps and deployment (medium + large)
- Environment strategy (dev, staging, prod)
- Deployment targets
- Monitoring and observability

### Interview completion

When all relevant sections are covered, use `AskUserQuestion`:

- "Show me the breakdown (Recommended)"
- "I have more to add"

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

Use the story template from `references/story-template.md`. It is short
on purpose: a Summary, the changes, and acceptance criteria, plus only
the sections that carry information the implementer would otherwise have
to guess. Where the plugin provides a `writing-github-issues` skill
(github-workflow does), read it before writing stories that become
GitHub issues, and follow it for the title as well as the body.

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

The final deliverable is epics and stories with acceptance criteria
and dependency ordering, presented in the conversation. The user can
then create issues, board items, or tickets in their project
management tool of choice. Do **not** write specification documents
to the filesystem — the conversation and the resulting GitHub issues
are the record.
