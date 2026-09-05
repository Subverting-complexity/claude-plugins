---
name: feature-discovery
description: >-
  Interview the user about a feature, change, plan, or design — whether or not
  a codebase is involved. Two modes: **discovery** (plan a feature and
  decompose it into user stories) and **validation** (stress-test a plan or
  design until every open question is resolved). Auto-detects the mode from
  context.

  Trigger whenever the conversation involves: scoping a feature, breaking work
  into stories, discussing a new story or requirement, challenging a plan or
  design, refining a backlog item, or any discussion where open questions about
  what to build or how to build it remain unresolved. Prefer triggering early —
  it is better to start the interview while context is fresh than to wait until
  the user explicitly asks.

  Do NOT use for scaffolding a new project (use repo-scaffolding), writing one
  story from notes (use user-story), implementing code (use execute), or
  reviewing code (use code-review).
depends-on:
  - code-architect
---
<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->

# Feature Discovery

Interview the user to resolve every open question about a feature, change,
plan, or design. Get to the core as fast as possible. Be relentless: probe
every vague answer, challenge weak reasoning, surface conflicts between
decisions, and don't move on until each question has a concrete answer or a
conscious deferral with a stated reason.

## Output standard

Everything a person reads — plans, questions, findings, summaries, and
anything posted or committed — follows `skills/_shared/wording-standard.md`
for how it reads, `skills/user-facing-communication/SKILL.md` for what it
contains and in what order (outcome and current state first, then anything
outstanding, blocked or assumed, every work item named as well as numbered,
no investigation history), and `skills/_shared/banned-patterns.md` for what
must never appear. Every reply, not only the last one.

## Skills Used

Read each skill's SKILL.md when you reach the phase that needs it.

- **code-architect** (`/local-workflow:code-architect`) — Architecture design and validation.

## Mode Detection

Determine the mode before starting. This drives whether the interview
produces stories or just resolves decisions.

| Mode | Signal | Output |
|------|--------|--------|
| **Discovery** | User wants to plan a feature, break work into stories, scope a change, decompose a requirement or ticket | Stories with acceptance criteria |
| **Validation** | User wants to stress-test a plan, challenge a design, poke holes in an approach, validate thinking, or refine an existing story | Conversation only — no files, no documents |

State the mode after detection: "I'll run this as a **discovery** session —
we'll end with stories." or "I'll run this as a **validation** session —
we'll work through every open question." The user can override.

When called as a refinement skill for a `needs-refinement` story, default
to **discovery** mode (the story needs fleshing out into actionable work).

## Scope Detection (discovery mode)

Determine scope before starting. This drives how deep the interview goes.

| Tier | Signal | Interview depth |
|------|--------|----------------|
| **Small** | Single concern: one endpoint, one screen, one config change, one bugfix | 3-5 questions. Scope, integration, edge cases. |
| **Medium** | Multi-concern feature: touches 2-4 modules, new user journey, new data model | 8-15 questions. Scope, journeys, data, integration, architecture. |
| **Large** | Major feature: new subsystem, significant rewrite, 5+ stories of work | Full interview. All sections. |

State the tier after research: "This looks like a medium-scope feature, so
I'll focus on scope, data model, and integration points." The user can
override.

In **validation** mode, skip scope detection — interview depth is driven
by the number of open questions, not feature size.

---

## Phase 1: Research

Before asking the user anything, gather what you can. The more you learn
here, the fewer questions you need to ask.

**When a codebase is available:**

1. Read the README, any project documentation, or config files for project structure, conventions, and context.
2. Read any backlog docs or task lists if accessible.
3. Explore the codebase: directory structure, key files, existing patterns, architectural approach.
4. Identify the modules, files, and patterns the feature will touch or extend.

**When no codebase is available** (plan validation, early-stage design):

1. Work from what the user has described so far.
2. Identify gaps, ambiguities, and unstated assumptions in their description.
3. Note any constraints or context clues from the conversation.

### Codebase exploration discipline

When the codebase can answer a question, explore it instead of asking. Use
file reads, search, and bash. Show a brief summary of what you found (file
name, relevant finding), state what you're recording based on that finding,
and continue. Do not silently resolve. Always show the user what was found.

### Research output

Present a brief summary of what you found:
- Relevant existing code and patterns (if codebase available)
- Related existing stories or tasks
- Potential integration points and constraints

Then state the mode and (for discovery) the scope tier and which interview
sections you plan to cover. Use `AskUserQuestion` to confirm:

- "Agree with scope (Recommended)" — proceed with the detected mode/tier
- "This is bigger than that" — bump up a tier
- "This is smaller" — bump down a tier

---

## Phase 2: Interview

### Interview posture

Be relentless. The goal is shared understanding with every open question
resolved. Don't accept hand-waving. If the user gives a surface-level
answer, dig deeper. If they say "probably" or "it depends", that's your
cue to probe until the answer is concrete or the user explicitly defers
(with a reason). In discovery mode, every resolved question informs the
stories. In validation mode, every resolved question strengthens the plan.
Every deferred question becomes a noted open issue.

### Wording and Clarity

Follow the shared `_shared/wording-standard.md` for every question,
recommendation, and `AskUserQuestion` option you write. The person
answering often has **no prior context** — the agent may be running
autonomously, so they have not seen the reasoning that led to the
question. The essentials:

- **State both the problem and the proposed solution.** Explain what is
  being decided and what you recommend doing about it, not just "which
  option?".
- **Write in complete sentences** and avoid telegraphic fragments.
- **Always include the why** in plain language.
- **Avoid or define jargon**, but keep precision — identifiers stay in
  backticks.
- This applies to `AskUserQuestion` option **labels and descriptions**,
  which are often all an autonomous reader sees.

Terse and hard to parse without context:

> Cache layer? Redis vs in-mem LRU, TTL 5m, invalidate on write.

Clear and easy to read:

> - **The problem:** Product lookups hit the database on every request,
>   and the catalogue page issues dozens of them per load.
> - **Recommendation:** Add a read-through cache in front of the
>   `ProductRepository`. I'd use the existing Redis instance rather than
>   an in-memory `LRU` cache, so the cache is shared across all server
>   instances. Entries would expire after 5 minutes by default, and we'd
>   clear an entry when its product is updated. Do you agree, or would
>   you prefer a different store or expiry?

See `_shared/wording-standard.md` for the full standard and a second
example.

### Interview mechanics

- **Lead with recommendations.** For every question, state what you'd recommend and why before asking. Don't just interrogate. Give your best answer based on codebase research, then ask if the user agrees or wants to change it.
- **Self-answer from the codebase.** Before asking anything, check if the codebase answers it. If it does, show what you found, state what you're recording, and move on. Only ask the user what the codebase can't tell you.
- **Batch related questions.** Group questions that belong to the same topic into a single turn. Don't artificially slow the interview down.
- **Push back on vague answers.** "It depends", "probably X", "we'll figure it out later" are not answers. Probe until concrete or explicitly deferred.
- **Flag conflicts.** If a later answer contradicts an earlier one, surface it immediately. Don't silently accept the contradiction.
- **Defer consciously.** If something genuinely can't be decided yet, note it as an open issue with a stated reason and move on. Never silently skip.
- **Track context.** Maintain a running internal record of resolved questions and deferrals as you go. This ensures nothing falls through the cracks during decomposition (discovery) or summary (validation).

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
- Word the question and every option per the Wording and Clarity rules
  above (`_shared/wording-standard.md`): each option label and
  description should convey the problem and the proposed solution to a
  reader with no prior context.

### Interview sections

**Only cover sections relevant to the scope tier (discovery) or the plan
being validated (validation).** Within each section, skip questions the
codebase already answered.

#### 1. Scope and boundaries (all tiers, both modes)
- What is being built or changed? (the user's opening message often covers this, don't re-ask)
- What's out of scope?
- Who are the affected users?

#### 2. User journeys (medium + large, or validation of user-facing plans)
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

#### 5. Integration points (all tiers, both modes)
- Which existing modules does this touch?
- Existing patterns to follow?
- Potential ripple effects on other features

#### 6. Architecture (large, or when trade-offs arise, or validation mode)
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

**Discovery mode:** When all relevant sections are covered, use `AskUserQuestion`:

- "Show me the breakdown (Recommended)"
- "I have more to add"

**Validation mode:** When all open questions have a resolved answer or
conscious deferral, present a summary of all decisions in the
conversation and propose closure. Do **not** write any files.

---

## Phase 3: Architecture (when needed)

Skip for small-scope work unless the user raises architecture concerns. For medium and large scope, use the **code-architect** skill to:
1. Design or validate the approach
2. Flag violations or tensions with existing architecture

---

## Phase 4: Decomposition (discovery mode only)

Skip this phase entirely in validation mode.

Break the work into stories (and optionally epics if the feature is large enough to warrant grouping).

### Epic structure (large scope only)

Each epic groups related stories. For each:
- Title (short, capability-focused)
- Goal (2-3 sentences)
- Dependencies on other epics

For small and medium scope, skip epics. Just produce stories.

### Story structure

Use the story template from `references/story-template.md`. It is short
on purpose: a Summary, the changes, and acceptance criteria, plus only
the sections that carry information the implementer would otherwise have
to guess. Where the plugin provides a `writing-github-issues` skill
(github-workflow does), read it before writing stories that become
GitHub issues, and follow it for the title as well as the body.

A story the interview left genuinely open keeps that uncertainty in the
words the interview used. Do not resolve an open question by writing a
decision into the story.

### Story sizing

- One session of work max (~100k tokens). If bigger, split it.
- One concern per story (one module, one screen, one API surface).
- Technical Notes over 10 lines means the story is too big.
- More than 5 files to create/modify means the story is too big.
- More than 3 modules touched means the story is too big.
- Dependencies must be explicit and acyclic.
- Assign a size estimate to each story: `small` (< 50k tokens),
  `medium` (50–100k), `large` (needs splitting). Include this in the
  story's Summary section as `**Size estimate:** {size}`.
- When a story is flagged as too large, automatically split it and
  explain the split to the user before proceeding.

### Deferred speccing (large features)

When a large-scope feature produces more than 4 stories:

1. **Fully spec** the first 2–3 stories in the dependency chain (the
   fundamentals that later stories depend on).
2. **Defer speccing** for stories deeper in the dependency chain.
   Create them with minimal spec: title, one-line Overview, dependency
   markers, and a note: "This story needs refinement after its
   dependencies are complete."
3. Apply the `needs-refinement` label (from the project's label map)
   to deferred stories. This excludes them from the execute pick pool
   until their dependencies are resolved and a refinement session has
   been run.

### Dependency chain enforcement

Every story must declare its dependencies explicitly using the format:
`Depends on #{number}` (or `Blocked by #{number}`, `After #{number}`).

After decomposition:

1. Build a text-based dependency graph showing the ordering.
2. Validate the graph is a DAG — no cycles allowed. If a cycle is
   detected, surface it to the user and resolve before proceeding.
3. Include the dependency graph in the Phase 5 review output.

### Cross-referencing

After decomposition, verify:
- Every interview question is covered by at least one story
- No gaps in the user journey
- Dependencies are acyclic (validated by the DAG check above)
- No overlap with existing stories
- Story ordering respects dependency chain

---

## Phase 5: Review (discovery mode only)

Skip this phase entirely in validation mode.

Present the plan before finalising:
1. Story list with one-line summaries (grouped by epic if applicable)
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

**Discovery mode:** The final deliverable is stories (optionally grouped
into epics) with acceptance criteria and dependency ordering. Do **not**
write decision documents, design specs, or summary files to the
filesystem. The conversation is the decision record; the stories are the
actionable output.

**Validation mode:** The conversation is the entire deliverable. Present
a summary of resolved decisions and open issues when the interview is
complete. Do **not** write any files.

### Creating issues on GitHub (discovery mode only)

When the user approves the plan, offer to create the stories as GitHub
issues. If they accept:

0. Write each title and body to the plugin's `writing-github-issues`
   standard (github-workflow provides it as a skill; its story shape is
   `references/story-template.md`). The interview produces far more
   material than a story needs, so this is where most of it gets left
   behind: no discovery history, no restating the Summary under another
   heading, and no section that would be empty.

   Check once, before the first issue, whether the repository publishes
   an issue template, either its own or one inherited from the
   organisation's `.github` repository. Where one applies, every story
   uses its headings and order. github-workflow resolves this through
   `templates/issue-template-resolution.md`; the result is cached, so
   check once rather than per story.
1. Create issues in **dependency order** — dependencies first so that
   later stories can reference them by issue number.
2. Include a `## Dependencies` section in each issue body listing
   upstream dependencies by issue number (e.g., `Depends on #42`).
3. Apply ready state based on dependency state:
   - Stories with no unresolved dependencies (DAG roots) → mark as
     ready per the project's `ready-gate` setting: apply the
     `status-ready` label and/or move to the "Ready" board column.
   - Stories whose dependencies are not yet closed →
     do NOT mark as ready. The `## Dependencies` section in the body
     is sufficient to communicate the dependency — no blocked label
     is needed.
   - Deferred stories (see "Deferred speccing") →
     `needs-refinement` label.
4. **Native type + fields** (best-effort, capability-gated) — labels alone
   leave an issue unclassified in the org's own views, so upgrade each
   created issue to the native issue type and the org's field values.
   Under github-workflow this is one call for the whole set, not a loop:
   write an update entry per issue and apply them together.

   ```bash
   mkdir -p .claude
   cat > .claude/discovery-spec.json <<'JSON'
   {"issues": [{"number": {number}, "kind": "{story|epic}",
                "parent": {epic number, when the story belongs to one},
                "blocked_by": [{upstream issue numbers}],
                "fields": {"field-priority": "{Urgent|High|Medium|Low}",
                           "field-effort": "{Low|Medium|High}",
                           "field-origin": "Feature Discovery"}}]}
   JSON
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-apply .claude/discovery-spec.json
   ```

   - `kind` supplies the native type **and** the `Classification` value
     together (a story → User Story / New Feature, an epic → Epic), so
     neither is chosen by hand. Use `spike` for a research story.
   - `field-effort` comes from the story's size estimate: large → **High**,
     medium → **Medium**, small → **Low**.
   - `field-priority` is set only where the plan assigned one, and stays
     dual-tracked with the `priority-*` label.
   - `blocked_by` writes a native edge **and** the body's `## Dependencies`
     prose, so the markers from step 2 stay authoritative.

   Read the exit code: **0** applied it; **21** (`no-capabilities`) means
   the org defines no types or fields, so the label-based result from the
   steps above stands with no error; **22** means the spec is wrong, so fix
   it and re-run; **23** and **24** mean the issues exist but some metadata
   did not land, so name what failed and carry on.

   Where the command is unavailable, say so and leave the label-based
   result — do not hand-write the mutations.
5. After creation, verify each issue body contains the correct
   dependency references. Use the post-creation validation pattern
   (see report-issue) to catch body corruption.
6. Present a summary: issue numbers, titles, native type/labels, and the
   dependency graph with issue numbers filled in.

**Leave the assignee blank.** Do not assign created stories to anyone —
not the creator, not an agent. Pass no `--assignee`/`--add-assignee` on
creation and do not edit issues to assign them afterward. Backlog
stories must enter the unassigned pool so `execute` can
select them; assignment happens only at claim time, never at creation.

---

## Continuous Mode

When the feature area already has stories:
1. Read all existing tasks and their status
2. Identify gaps (missing stories, stale stories, incomplete AC)
3. Present findings
4. Interview only for the gaps
5. Produce only the missing stories
