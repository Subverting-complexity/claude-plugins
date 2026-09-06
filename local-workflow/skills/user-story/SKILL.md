---
name: user-story
description: "Write or format a single user story for a development work item, with acceptance criteria. Use when the user wants to spec out a feature, write up a ticket, or turn rough notes into a structured story. Do NOT use for breaking a feature into multiple stories (use feature-discovery) or scaffolding a new project (use repo-scaffolding)."
---
<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->

# User Story Documentation

Read `_shared/wording-standard.md` and `_shared/banned-patterns.md` before writing. Both apply to user stories. Assume a technically capable reader who is not involved in this codebase: explain what a component or pattern is before relying on its name, and never let a string of identifiers replace a plain explanation.

`skills/user-facing-communication/SKILL.md` shapes what you say to the
person **around** the story: lead with the outcome and the current
state, keep it short, and surface anything outstanding or assumed. It
governs your reply, not the story itself.

**If the story is going into a GitHub issue, the issue standard wins.**
The format below is built for pasting into a project management tool.
When the destination is a GitHub issue, write it to the plugin's
`writing-github-issues` standard instead (github-workflow provides it as
a skill, with the story shape in `references/story-template.md`): a
`## Summary` that stands on its own, then only the sections that carry
information. Ask which one you are producing if it is not clear from the
request.

Whichever destination it has, the story is a tracker body, so
`_shared/body-standard.md` applies: standard section names, plain
sentences, exact identifiers, and **each paragraph on one unwrapped
line**. Never break prose at 72, 80 or any other column.

Write user stories that give developers a clear picture of what to build and why. Every story follows the same structure so readers know exactly where to look: a business-facing Overview and an implementation-focused Technical section.

## Output Format

The entire output must be wrapped in code blocks so the user can copy/paste directly into their project management tool. This is critical: every section goes inside its own fenced code block (triple backticks). Do not output raw markdown headers outside of code blocks.

1. **Title block**: The title on its own line, inside a code block
2. **Body block**: The full markdown body (Overview, Technical) inside a separate code block
3. **Acceptance criteria block** (only when requested): Testing criteria inside a separate code block

If the user already has a user story and only needs acceptance criteria, return just the acceptance criteria code block.

Example output shape (note: each section is inside triple backticks):

```
Dual-Axis Graph Type
```

```
## Overview
[Business summary]

---

## Technical
[Implementation details]
```

```
## Acceptance Criteria
[What to test]
```

This format lets the user copy each piece separately without selecting text.

## Structure

### Title

A short, descriptive title. No prefix. Keep it under 10 words. Focus on the capability being added or changed.

Examples:
- Dual-Axis Graph Type
- Category Splitting for Stand-Alone Metrics
- AI Progress Summary Field and Enrichment Pipeline
- Internal Test Run Parameters for User Scripts

### Overview

The Overview is for anyone reading the story, not just developers. It answers: what are we adding, and why does it matter?

Include:
- What the feature enables in plain language
- The business value or use case (who benefits and how)
- A high-level description of what the implementation involves, without going deep into specifics

Write as prose. Keep it to one or two short paragraphs. If the feature is visual, mention that screenshots or mockups are attached (the user will add these separately).

### Technical

The Technical section is the implementation plan. It tells a developer what to build and what to keep in mind.

**Match the depth of the input.** If the user gives a high-level idea ("add a category field to metrics"), write a concise technical plan with the key decisions called out. If the user gives detailed notes with field names, JSON structures, and edge cases, reflect that detail in the output. The goal is to capture what the user knows without padding or trimming.

Common elements in a Technical section (include what's relevant):

- **UI changes**: What controls to add, where they go, how they behave. Use the component's actual name if known.
- **Data structure / JSON**: When the feature involves configuration or schema changes, show the relevant JSON structure. Include enough to be unambiguous, not necessarily every field.
- **Rules and constraints**: Validation rules, field relationships, edge cases to handle.
- **Backend changes**: API changes, new fields, new tables, new scripts.
- **Scope boundaries**: What's explicitly out of scope (e.g., "downstream Python logic is out of scope for this story").

Organize with subheadings when the technical section covers multiple areas (UI, JSON, Backend, etc.). For simpler stories, bullets under a single Technical heading are fine.

### Acceptance Criteria (only when requested)

Acceptance criteria are written for **end users and testers**, not developers. The reader may not have technical knowledge, so avoid mentioning backend implementation details (C# classes, API internals, database migrations). Focus on what the user sees and does in the UI.

The exception: when the feature produces user-visible configuration output (like JSON in a config editor), include that in the criteria because the user interacts with it directly.

Structure:
- Lead with a one-line summary describing what was added and where
- Use a bold "**What should be tested**" heading
- Each item is a specific user action and its expected result
- Use sub-bullets for the expected outcome when it needs to be distinct from the action
- Cover the happy path first, then state changes (switching away and back), then edge cases (empty/null states)
- Include example JSON when the feature generates config output the user can inspect

**Example 1: Config feature with JSON output**

```
## Acceptance Criteria

A new **Dual Axis** graph type has been added to the **Generic Configuration Parameter > Graph section** when editing graphs. This option allows a graph to display two Y-axes and enables additional configuration fields for the secondary axis.

**What should be tested**
- The graph type selector includes the new **Dual Axis** option.
- Selecting **Dual Axis** displays additional fields for:
  - Secondary Y Fields
  - Secondary Axis Label
  - Secondary Data Type
  - Secondary Format
- Values can be entered into these secondary axis fields and saved.
- Changing the graph type **from Dual Axis to another graph type**:
  - Clears the secondary axis fields in the UI.
- Switching **back to Dual Axis**:
  - Secondary axis fields remain empty and must be reconfigured.
- Saving a graph with **Dual Axis selected** stores the secondary axis configuration in the JSON.

Example JSON structure:
```json
{
  "graphType": "Dual Axis",
  "yFields": ["Net Sales"],
  "y2Fields": ["Transactions"],
  "y2Label": "Secondary Y Axis Label",
  "secondaryDataType": "Integer",
  "secondaryFormat": {
    "decimalPlaces": 0
  }
}
```

- When the graph type is **not Dual Axis**, the JSON should contain blank or null values for:
  - `y2Fields`
  - `y2Label`
  - `secondaryDataType`
  - `secondaryFormat`
```

**Example 2: Simple UI feature**

```
## Acceptance Criteria

A **Category Field** option has been added when editing **Metrics** inside the **Generic Configuration Parameter**.

**What should be tested**
- When editing a **Metric** in the **Generic Configuration Parameter**, a **Category Field** dropdown is available.
- Select **Store Type** as the **Category Field**, save the configuration, and reopen it.
  - The **Category Field** should still be **Store Type**.
- After saving, confirm the configuration stores the category field correctly.
  - The configuration should include `"categoryField": "Store Type"`.
- Ensure the configuration can still be saved when **Category Field** is not selected.
```

## Multi-Part Stories

Some features span multiple systems or steps (e.g., new field + extraction + enrichment + reporting). When the input describes a multi-part effort:

- Use numbered or named sections under Technical, one per logical component
- Each section should be self-contained enough that a developer could pick it up independently
- Order them in the sequence they'd naturally be implemented (dependencies first)

## Formatting Rules

1. **Bold** system names, component names, field names, and UI element names on first mention
2. Use `code formatting` for field values, JSON property names, config values, and technical identifiers
3. No em dashes anywhere in the output. Replace with commas or split into two sentences. This includes the Overview, Technical, and Acceptance Criteria sections.
4. No filler phrases ("We need to", "The idea is to", "Basically")
5. Lead with what's being built, not the backstory of why
6. Horizontal rules (`---`) separate Overview from Technical
7. Use JSON code blocks when showing config structures, with realistic but clearly example data
8. Use markdown tables (not bullet lists) when showing database schemas, column definitions, or any structure with multiple attributes per item. For example, a table with columns should be presented as a table with Column, Type, and Description headers.

## When Rewriting Existing Content

If given rough notes or an existing write-up to clean up:
1. Identify the overview, technical plan, and any acceptance criteria
2. Rewrite into the standard structure
3. Cut filler and redundancy
4. Bold key identifiers
5. Organize technical details under appropriate subheadings
6. Preserve all technical specifics from the original (field names, JSON structures, query examples)
