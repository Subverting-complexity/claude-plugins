<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->
---
name: repo-scaffolding
description: "Scaffold a new project or repository from scratch: full discovery, architecture, and story decomposition into epics and user stories with acceptance criteria. Use when the user wants to plan a brand-new project, set up a new repo, scaffold a codebase, or design a system from the ground up. Trigger on: 'scaffold this', 'new project', 'set up a repo', 'plan a new app', 'build this from scratch', 'greenfield project', 'design a new system', 'start a new codebase', 'I want to build X', 'spin up a project for X'. Also trigger when the user describes a product idea or system concept and wants it broken down into buildable work. Do NOT use for adding features to an existing codebase (use feature-discovery instead). Do NOT use for building or implementing code (use execute instead)."
---

# Repo Scaffolding

Plan and decompose a new project into epics and user stories. Get to the core of the design as fast as possible. The interview should be relentless: probe every vague answer, challenge weak reasoning, surface conflicts between answers, and don't move on until each question has a concrete answer or a conscious deferral with a stated reason.

## Skills Used

Read each skill's SKILL.md when you reach the phase that needs it.

- **code-architect** (`/local-workflow:code-architect`) — Architecture design and validation.

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

Present a brief summary of what you found, then state the scope tier and which interview sections you plan to cover. This is the first decision point:

> `Agree with scope` · `This is bigger than that` · `This is smaller`

---

## Phase 2: Interview

### Interview posture

Be relentless. The goal is shared understanding with every open question resolved. Don't accept hand-waving. If the user gives a surface-level answer, dig deeper. If they say "probably" or "it depends", that's your cue to probe until the answer is concrete or the user explicitly defers (with a reason). Every resolved question informs the stories. Every deferred question becomes a noted open issue.

### Interview mechanics

- **Lead with recommendations.** For every question, state what you'd recommend and why before asking. Don't just interrogate. Give your best answer, then ask if the user agrees or wants to change it. Tappable options should reflect your recommendation as the first choice.
- **Batch related questions.** Group questions that belong to the same topic into a single turn. Use multiple `interactive selection` calls per turn when they cover related topics. Don't artificially slow the interview down.
- **Push back on vague answers.** "It depends", "probably X", "we'll figure it out later" are not answers. Probe until concrete or explicitly deferred.
- **Flag conflicts.** If a later answer contradicts an earlier one, surface it immediately. Don't silently accept the contradiction.
- **Defer consciously.** If something genuinely can't be decided yet, note it as an open issue with a stated reason and move on. Never silently skip.
- **Track context.** Maintain a running internal record of resolved questions and deferrals as you go. This ensures nothing falls through the cracks during decomposition.

### Tappable options

Use `interactive selection` for any question with a bounded answer set: binary choices, picking from discovered patterns, confirming recommendations, scope in/out calls, phase-gate confirmations.

- 2-4 options, short labels.
- If you find yourself writing an "Other" option because the real answer probably isn't in the list, ask in plain text instead.
- If the user types instead of tapping, that's their answer.

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

When all relevant sections are covered:
> "I think we've covered everything needed to break this down."
>
> `Show me the breakdown` · `I have more to add`

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

Each story is a single-session unit of work for an autonomous agent. Use the 12-section issue template, omitting sections that don't apply:

```markdown
## Overview
What this story delivers and why. 2-4 sentences.

## User Role
Which user type(s) this story serves.

## Business Rules
Concrete, testable rules. Numbered list.

## Acceptance Criteria
- [ ] Specific, verifiable criterion
- [ ] Agent can self-evaluate each one

## Edge Cases
- Scenario → Expected behavior

## Data Model
Tables/entities this story creates or modifies.
Markdown tables for columns (Column | Type | Description).

## API Contract
Endpoints created or modified.
Method, path, request/response, status codes, auth.

## UI/UX Requirements
Screen location, user flow, states (loading/empty/error/success).

## Dependencies
- Preceding stories (by title or reference)
- External dependencies

## Technical Notes
Files affected, approach, which layer, which patterns to follow.
Specific enough for an agent with no prior context.

## Testing Requirements
- Test type, what's tested, key assertions
- No generic placeholders

## Definition of Done
- [ ] Code complete and committed
- [ ] All acceptance criteria met
- [ ] All tests pass
- [ ] Quality gate passes
```

**Omit empty sections.** The template is a maximum, not a minimum.

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

> `Approve` · `I have changes` · `Redo a section`

Iterate until confirmed.

---

## Phase 6: Specification Documents (large scope only)

For large-scope projects, produce three spec documents:

**Business Design Overview** (`*_Business_Design_Overview.md`)
Problem, solution, users, business model, metrics, competitive landscape.

**Requirements Specification** (`*_Requirements_Specification.md`)
Features by area, business rules, permissions, compliance, NFRs.

**Technical Specification** (`*_Technical_Specification.md`)
Architecture, stack, data model, API design, infrastructure, security.

Naming: `<Project>_<Version>_<Document_Type>.md`

Skip this phase for small and medium scope unless the user asks for it.

---

## Output

The final deliverable is epics and stories with acceptance criteria and dependency ordering. The user can then create issues, board items, or tickets in their project management tool of choice.
