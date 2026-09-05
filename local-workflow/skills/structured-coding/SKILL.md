---
name: structured-coding
description: "Methodology for approaching any coding task with discipline and structure — bug fixes, new features, refactors, or architecture changes. Use whenever the user wants code written or modified, even small changes. Note: execute calls this as its build phase; prefer execute when the user wants end-to-end task execution (plan, build, verify, commit)."
allowed-tools:
  - Read
  - Edit
  - Write
  - Glob
  - Grep
  - Bash(git diff *)
  - Bash(git status *)
  - Bash(cat *)
  - Bash(ls *)
  - Bash(find *)
  - Bash(grep *)
  - Bash(rg *)
---
<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->

# Structured Coding

This skill defines how to approach coding tasks. The core philosophy: understand before you act, define before you build, and write code that belongs in its codebase.

## Output standard

Everything a person reads — plans, questions, findings, summaries, and
anything posted or committed — follows `skills/_shared/wording-standard.md`
for how it reads, `skills/user-facing-communication/SKILL.md` for what it
contains and in what order (outcome and current state first, then anything
outstanding, blocked or assumed, every work item named as well as numbered,
no investigation history), and `skills/_shared/banned-patterns.md` for what
must never appear. Every reply, not only the last one.

## Current session state (auto-loaded)

**Branch:** !`git branch --show-current 2>/dev/null || echo "(not a git repo or detached HEAD)"`

```!
echo "--- Uncommitted changes ---"
git diff --stat HEAD 2>/dev/null || echo "(no git repo)"
echo ""
echo "--- Recent commits on this branch ---"
git log --oneline -5 2>/dev/null || echo "(no commits)"
```

## The Approach

Every coding task — no matter how small — follows this sequence:

1. **Understand the landscape** — What does the codebase look like at a high level? What patterns, conventions, and architecture decisions are already in place?
2. **Understand the target** — Deeply understand the specific area being changed. Read the surrounding code. Know what it does, why it exists, and how it connects to the rest of the system.
3. **Define the goal** — What exactly needs to happen, and what does "done" look like?
4. **Plan the path** — How will you get there? What needs to change, in what order?
5. **Write the code** — Only now do you write. And you write code that fits.

Skipping steps 1–4 is how bugs, regressions, and tech debt are born. Resist the urge to jump straight to code.

---

## Step 1: Understand the Landscape

Before touching anything, build a mental model of the codebase. You're looking for:

- **Architecture**: How is the project organized? What are the major modules/layers? Is it a monolith, microservices, MVC, feature-sliced?
- **Patterns**: How do existing features handle similar concerns? State management, error handling, API calls, data flow — what conventions are already established?
- **Style**: Naming conventions, file structure, import ordering, formatting. The codebase has a voice; learn it before you speak in it.
- **Dependencies**: What libraries and tools are in play? Don't reinvent what's already available, and don't introduce a new dependency when the codebase already has a way to do it.

If the user has shared files or a repo, read the project structure and key files first. If you only have a snippet, ask what you need: "What framework is this in? How is the project structured?" Getting this context upfront saves everyone time.

## Step 2: Understand the Target

Now zoom in. Read the specific code that will be affected — not just the function or file, but its connections:

- What calls this code? What does this code call?
- What assumptions does it make about its inputs and outputs?
- Are there tests? What do they tell you about intended behavior?
- Are there edge cases already being handled that you need to preserve?

If you don't have enough of the codebase to understand the target area deeply, ask for it. Say something like: "Can you share the file where X is defined? I want to make sure the change fits with how it's used."

## Step 3: Define the Goal

Every task needs a clear definition of what "done" means. Before writing any code, always present the user story to the user in this exact structure:

```
## Overview
[High-level explanation of what needs to happen and why. The "what" and the "so that." Keep it plain language — this is the summary a non-technical stakeholder could read and understand.]

## Technical
[What exactly needs to change in the code. Which files, which functions, what the approach is, what data flows are affected, and any technical considerations or trade-offs worth noting.]

## Acceptance Criteria
[Concrete, testable conditions that must all be true for the task to be considered complete. Each criterion should be specific enough that someone could verify it with a yes/no answer.]
```

This structure is **always** surfaced to the user — for every task, no matter how small. A one-line bug fix still gets an overview ("Fix the off-by-one error in pagination"), a technical section ("Change the offset calculation in `getPage()` from `page * size` to `(page - 1) * size`"), and acceptance criteria ("Page 1 returns the first N results, not the second N"). The depth scales with the task, but the structure is always there.

Present this to the user and get confirmation before writing code —
unless you are executing inside an autonomous workflow (e.g.,
`/local-workflow:build`) that explicitly says not to pause. In
that case, the issue requirements and architecture plan serve as the
approved specification — proceed directly to Step 4.

When the user's request is vague or ambiguous, ask clarifying questions to fill in the gaps in this structure before presenting it. Shape your questions around what's missing:

- If the overview is unclear: "What's the actual problem you're trying to solve here?"
- If the technicals are unclear: "How should this interact with [existing system]?"
- If acceptance criteria are missing: "How will you know this is working correctly? What should happen in [edge case]?"

Don't ask all of these at once — focus on the gaps that actually block you from building a confident user story.

## Step 4: Plan the Path

Before writing code, think through the implementation:

- **Break it down**: If the task involves multiple logical changes, split it into discrete steps. Each step should be independently understandable and, ideally, independently testable. Share this breakdown with the user when there are more than two or three steps — it's a checkpoint that catches misalignment early.
- **Sequence matters**: Order your changes so that each step builds on a working state. Don't make five changes at once that are hard to debug together.
- **Identify risks**: What could go wrong? What existing behavior might break? Call these out proactively.

## Step 5: Write the Code

Now you write — and the code should look like it was always part of the codebase.

### Follow existing patterns
This is non-negotiable. If the codebase uses a particular pattern for API calls, error handling, state management, or component structure — use that same pattern. Consistency across a codebase is more valuable than your preferred approach. The only exception is when the existing pattern is actively broken or harmful, and even then, flag it and discuss before deviating.

### Write robust code
- Handle errors explicitly. Don't let failures happen silently.
- Validate inputs where appropriate, especially at system boundaries (API endpoints, user input, external data).
- Consider edge cases: null/undefined values, empty collections, concurrent access, network failures.
- Don't just handle the happy path. Think about what happens when things go wrong.

### Keep it clean
- Names should be descriptive and consistent with the codebase's conventions. A reader should understand what something does from its name.
- Functions should do one thing well. If a function is doing three things, it's probably three functions.
- Keep the scope of changes minimal. Don't refactor unrelated code in the same change unless that's the explicit goal.

### Comments: less is more
Comments exist to explain *why*, not *what*. If the code needs a comment to explain what it does, the code should probably be rewritten to be clearer. Good reasons for comments:

- Explaining a non-obvious business rule ("We exclude weekends because the billing system only processes on business days")
- Documenting a workaround ("This works around a bug in library X v2.3 — remove when we upgrade")
- Clarifying genuinely complex algorithms where the logic can't be simplified further
- Legal or licensing requirements

Bad reasons for comments:
- Restating what the code does (`// increment counter` above `counter++`)
- Marking sections that should be separate functions
- Explaining confusing code that could be made clear through better naming

---

## Asking for Clarification

When a user's request is unclear, don't guess — ask. But ask smart:

- Restate what you *do* understand, then ask about what's missing. This shows you've engaged with the problem and narrows the conversation.
- If you can infer a likely answer, propose it: "I'm assuming you want X because of Y — is that right?" This is faster than an open-ended question.
- Don't interrogate. One or two focused questions per response. If you need more context, get it iteratively.

The goal is to reach a clear user story (overview, technicals, acceptance criteria) as quickly as possible, whether the user hands it to you neatly or you assemble it from a rough description.

---

## Task Breakdown

When a task is large enough to involve multiple logical changes, break it into sub-tasks. Present the top-level user story first (Overview, Technical, Acceptance Criteria for the whole effort), then list the sub-tasks. Each sub-task gets its own user story with the same structure — scaled down in depth, but the same three sections.

Present this to the user as a plan and get confirmation before starting. This gives the user a chance to reprioritize, cut scope, or flag dependencies you missed. It also creates natural checkpoints — after each sub-task, present the next sub-task's user story and confirm before continuing.

---

## Summary of Principles

- Understand the whole before changing a part.
- Define the goal before writing the code.
- When in doubt, ask — don't assume.
- Code should fit its codebase like it was always there.
- Robust code handles failure, not just success.
- Comments explain the non-obvious; clear code explains itself.
- Break big work into small, verifiable steps.
