<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->
---
name: feature-discovery
description: "Plan a single feature, enhancement, or change within an existing codebase by interviewing the user, exploring the code, and producing user stories with acceptance criteria. Use ANY time the user wants to scope a feature, break a change into stories, plan a piece of work, do discovery on a feature, or figure out what tasks are needed for a specific change. Trigger on: 'discover', 'plan this feature', 'scope this out', 'break this into stories', 'what stories do we need', 'what tasks does this need', 'plan this change', 'what needs to be built', 'figure out what we need', 'do discovery on this', 'I want to add X'. Also trigger when the user shares a requirement, ticket, or spec and wants it decomposed into actionable work items. Do NOT use for scaffolding a new project from scratch (use repo-scaffolding instead). Do NOT use for writing a single formatted user story from existing notes (use user-story instead). Do NOT use for building or implementing code (use execute instead)."
---

# Feature Discovery

Plan and decompose a feature or change into user stories. Get to the core of the design as fast as possible. The interview should be relentless: probe every vague answer, challenge weak reasoning, surface conflicts between decisions, and don't move on until each question has a concrete answer or a conscious deferral with a stated reason.

## Skills Used

Read each skill's SKILL.md when you reach the phase that needs it.

- **code-architect** (`/github-workflow:code-architect`) — Architecture design and validation.

## Scope Detection

Determine scope before starting. This drives how deep the interview goes.

| Tier | Signal | Interview depth |
|------|--------|----------------|
| **Small** | Single concern: one endpoint, one screen, one config change, one bugfix | 3-5 questions. Scope, integration, edge cases. |
| **Medium** | Multi-concern feature: touches 2-4 modules, new user journey, new data model | 8-15 questions. Scope, journeys, data, integration, architecture. |
| **Large** | Major feature: new subsystem, significant rewrite, 5+ stories of work | Full interview. All sections. |

State the tier after research: "This looks like a medium-scope feature, so I'll focus on scope, data model, and integration points." The user can override.

---

## Phase 1: Research (always do this first)

Before asking the user anything, gather what you can. The more you learn here, the fewer questions you need to ask.

1. Read the README, any project documentation, or config files for project structure, conventions, and context.
2. Read any backlog docs or task lists if accessible.
3. Explore the codebase: directory structure, key files, existing patterns, architectural approach.
4. Identify the modules, files, and patterns the feature will touch or extend.

### Codebase exploration discipline

When the codebase can answer a question, explore it instead of asking. Use file reads, search, and bash. Show a brief summary of what you found (file name, relevant finding), state what you're recording based on that finding, and continue. Do not silently resolve. Always show the user what was found.

### Research output

Present a brief summary of what you found:
- Relevant existing code and patterns
- Related existing stories or tasks
- Potential integration points and constraints

Then state the scope tier and which interview sections you plan to cover. First decision point:

> `Agree with scope` · `This is bigger than that` · `This is smaller`

---

## Phase 2: Interview

### Interview posture

Be relentless. The goal is shared understanding with every open question resolved. Don't accept hand-waving. If the user gives a surface-level answer, dig deeper. If they say "probably" or "it depends", that's your cue to probe until the answer is concrete or the user explicitly defers (with a reason). Every resolved question informs the stories. Every deferred question becomes a noted open issue.

### Interview mechanics

- **Lead with recommendations.** For every question, state what you'd recommend and why before asking. Don't just interrogate. Give your best answer based on codebase research, then ask if the user agrees or wants to change it. Tappable options should reflect your recommendation as the first choice.
- **Self-answer from the codebase.** Before asking anything, check if the codebase answers it. If it does, show what you found, state what you're recording, and move on. Only ask the user what the codebase can't tell you.
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

**Only cover sections relevant to the scope tier.** Within each section, skip questions the codebase already answered.

#### 1. Scope and boundaries (all tiers)
- What is being built or changed? (the user's opening message often covers this, don't re-ask)
- What's out of scope?
- Who are the affected users?

#### 2. User journeys (medium + large)
- Happy path end-to-end
- Critical failure modes
- Edge cases

#### 3. Data model (medium + large, skip if no new entities)
- New entities and relationships
- Changes to existing entities
- Migration strategy if modifying existing data

#### 4. API surface (medium + large, skip if no new endpoints)
- Endpoints created or modified
- Auth/permission changes
- Contract changes and backwards compatibility

#### 5. Integration points (all tiers)
- Which existing modules does this touch?
- Existing patterns to follow?
- Potential ripple effects on other features

#### 6. Architecture (large, or when trade-offs arise)
- Patterns and trade-offs
- Constraints
- Deviations from existing architecture (and why)

#### 7. Dependencies and ordering (medium + large)
- Build order for stories
- External dependencies
- Prerequisite changes (migrations, config, infrastructure)

#### 8. Testing strategy (large, or when the user raises it)
- Critical paths needing integration tests
- Edge cases to cover
- Existing test patterns to follow

### Interview completion

When all relevant sections are covered:
> "I think we've covered everything needed to break this down."
>
> `Show me the breakdown` · `I have more to add`

---

## Phase 3: Architecture (when needed)

Skip for small-scope work unless the user raises architecture concerns. For medium and large scope, use the **code-architect** skill to:
1. Design or validate the approach
2. Flag violations or tensions with existing architecture

---

## Phase 4: Decomposition

Break the work into stories (and optionally epics if the feature is large enough to warrant grouping).

### Epic structure (large scope only)

Each epic groups related stories. For each:
- Title (short, capability-focused)
- Goal (2-3 sentences)
- Dependencies on other epics

For small and medium scope, skip epics. Just produce stories.

### Story structure

Use the story template from `references/story-template.md`.

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
- No overlap with existing stories
- Story ordering respects dependency chain

---

## Phase 5: Review

Present the plan before finalising:
1. Story list with one-line summaries (grouped by epic if applicable)
2. Dependency graph (text or visual)
3. Coverage check against interview findings
4. Open issues or deferred items

> `Approve` · `I have changes` · `Redo a section`

Iterate until confirmed.

---

## Output

The final deliverable is stories (optionally grouped into epics) with acceptance criteria and dependency ordering. The user can then create issues, board items, or tickets in their project management tool of choice.

---

## Continuous Mode

When the feature area already has stories:
1. Read all existing tasks and their status
2. Identify gaps (missing stories, stale stories, incomplete AC)
3. Present findings
4. Interview only for the gaps
5. Produce only the missing stories
