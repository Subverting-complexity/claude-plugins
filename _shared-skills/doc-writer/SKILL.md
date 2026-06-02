---
name: doc-writer
description: "Write or update project documentation: README, API docs, architecture guides, migration guides, and changelogs. Use when the user says 'write docs', 'update the README', 'document this', 'write API documentation', 'create a migration guide', 'generate docs', 'write an architecture guide', or 'update the changelog'. Also trigger on 'help me document', 'write up how this works', or 'explain this system in docs'. Do NOT use for code comments (those go in the code itself), PR descriptions (use pr-description), or user stories (use user-story)."
allowed-tools:
  - Read
  - Edit
  - Write
  - Glob
  - Grep
  - Bash(git log *)
  - Bash(git diff *)
  - Bash(git show *)
  - Bash(cat *)
  - Bash(ls *)
  - Bash(find *)
---

# Documentation Writer

Write or update project documentation based on the actual codebase.
Documentation describes what exists — do not document aspirational
features or planned changes.

Read `skills/_shared/banned-patterns.md` before writing. All
documentation must follow those voice and tone rules.

## Inputs

Determine the documentation type from the user's request:

- **README** — Project overview, setup, usage
- **API docs** — Endpoint or function reference
- **Architecture guide** — System design, component boundaries, data flow
- **Migration guide** — Upgrade steps between versions
- **Changelog** — What changed and why
- **How-to guide** — Step-by-step procedure for a specific task

If the type is ambiguous, ask.

## Phase 1 — Research

Before writing, understand what you're documenting.

1. **Read the code.** The codebase is the source of truth. Read entry
   points, public APIs, key modules, config files, and test files to
   understand behavior.
2. **Read existing docs.** Check for README, docs/, wiki references,
   inline JSDoc/docstrings, and OpenAPI specs. Understand what already
   exists so you extend rather than duplicate.
3. **Read git history** for context on recent changes (changelogs and
   migration guides).

## Phase 2 — Structure

Choose the right structure for the documentation type:

### README
1. One-sentence description (what this project does)
2. Quick start (install, configure, run — minimal steps)
3. Usage examples (common operations with code blocks)
4. Configuration reference (if applicable)
5. Contributing (if applicable)

### API docs
For each endpoint or public function:
1. Signature (method, path, parameters, return type)
2. Description (one sentence — what it does)
3. Parameters table (name, type, required, description)
4. Response format (with example)
5. Error responses (status codes and meanings)

### Architecture guide
1. System overview (one paragraph + diagram description)
2. Component map (what each major module/service does)
3. Data flow (how requests/data move through the system)
4. Key decisions
5. Boundaries (what talks to what, what's off-limits)

### Migration guide
1. Breaking changes (what will fail after upgrade)
2. Step-by-step upgrade procedure
3. Configuration changes required
4. Rollback procedure

### Changelog
Follow Keep a Changelog format:
- Added, Changed, Deprecated, Removed, Fixed, Security
- Most recent version first
- Each entry: one line, past tense, what changed and why

## Phase 3 — Write

1. **Be concrete.** Use real file names, real command output, real
   config values from the project. Do not use placeholder examples
   when real ones are available.
2. **Be accurate.** Every command in the docs should actually work.
   Every file path should exist. Every API example should match the
   real response format.
3. **Be brief.** One sentence where one sentence suffices. Code blocks
   over prose for anything procedural. Tables over lists for
   structured data.
4. **Update, don't replace.** If docs already exist, modify them to
   reflect the current state. Preserve sections the user may have
   customized (contributing guidelines, license, badges).

## Phase 4 — Verify

1. **Check all file paths** referenced in the docs actually exist.
2. **Check all commands** by running them if possible.
3. **Check for staleness** — if the docs reference features, config
   options, or APIs, verify they still exist in the current code.
4. **Read the result** end-to-end as a new user would. Does it make
   sense without prior context?
