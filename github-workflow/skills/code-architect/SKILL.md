<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->
---
name: code-architect
description: >-
  Design, audit, and document codebases using Clean Architecture, Design Patterns (GoF), and Fundamentals of Software Architecture. Three workflows. (1) Design new systems with architecture style selection, SOLID, testability, boundaries. Auto-triggers grill-me for requirements. (2) Audit existing code for SOLID violations, dependency direction, testability, with file-level findings and refactoring plans. (3) Produce architecture documentation - compliance guardrails, coding standards, boundary maps, and agent-followable strategy docs. Trigger on design/architect/structure a codebase, review/audit architecture, SOLID violations, dependency inversion, improve testability, refactor for extensibility, document the architecture, write coding standards, generate compliance rules, guardrails, architecture strategy. Also trigger when the user types "/code-a" as a slash command shortcut. Uses document-reader for book lookups.
depends-on:
  - grill-me
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash(find *)
  - Bash(cat *)
  - Bash(ls *)
  - Bash(head *)
  - Bash(tail *)
---

# Code Architect Skill

Design, audit, and document codebases using principles from Clean Architecture, Design Patterns, and Fundamentals of Software Architecture.

## Project structure (auto-loaded)

```!
echo "--- Key config files ---"
find . -maxdepth 2 -type f \( -name "*.json" -o -name "*.yaml" -o -name "*.yml" -o -name "*.toml" -o -name "*.csproj" -o -name "*.sln" -o -name "*.mod" -o -name "Makefile" -o -name "Dockerfile" \) ! -path '*/node_modules/*' ! -path '*/.git/*' 2>/dev/null | head -20
echo ""
echo "--- Top-level directories ---"
ls -d */ 2>/dev/null | head -20
echo ""
echo "--- Source structure (depth 2) ---"
find . -maxdepth 2 -type d ! -path '*/node_modules/*' ! -path '*/.git/*' ! -path '*/.*' 2>/dev/null | sort | head -30
```

## Core Workflows

### Workflow 1: Design New Codebase
When user asks to design, architect, or build a new system/codebase:

1. **Establish shared understanding** - Call the `grill-me` skill to clarify
   (skip this step when called from an autonomous workflow like
   `/github-workflow:execute` that explicitly says not to pause or call
   grill-me):
   - What problem does this solve?
   - Who are the users/actors?
   - What are the core business rules?
   - What are the critical quality attributes (scalability, maintainability, testability, performance)?
   - What are the constraints (technology stack, team size, timeline)?
   - What will change frequently vs. what's stable?

2. **Design the architecture**:
   - Identify bounded contexts and responsibilities
   - Define boundaries and dependency flow (dependencies point inward toward business logic)
   - Choose architecture style based on characteristics (layered, microservices, event-driven, etc.)
   - Apply SOLID principles at component level
   - Define testability strategy (isolate business logic from frameworks/infrastructure)

3. **Document the design**:
   - Core entities and use cases
   - Component diagram with dependency directions
   - Layer/boundary definitions
   - Key architecture decisions and trade-offs
   - Extensibility points

### Workflow 2: Audit Existing Codebase
When user asks to review, audit, or improve existing code:

1. **Scan the codebase** - Explore:
   - Directory structure and organization
   - Dependencies between modules/components
   - Business logic location (is it isolated or mixed with frameworks?)
   - Test coverage and testability

2. **Audit against principles** - Check for violations of:
   - **SOLID Principles** (read `references/clean-architecture.md` for definitions)
   - **Component Principles** (REP, CCP, CRP, ADP, SDP, SAP)
   - **Dependency Rule** - Do dependencies point toward business logic?
   - **Boundaries** - Are database, UI, frameworks separated from business rules?
   - **Testability** - Can business logic be tested without frameworks/infrastructure?

3. **Generate findings**:
   - List specific violations with file/line references
   - Explain why each is a problem
   - Suggest concrete refactoring steps
   - Prioritize by impact

4. **Propose refactoring plan**:
   - Break into incremental steps
   - Show before/after structure
   - Highlight extensibility gains

### Workflow 3: Produce Architecture Documentation
When user asks for architecture docs, strategy documents, compliance guardrails, coding standards, or any document that agents or developers should follow:

This workflow produces structured, enforceable documents. The key distinction: these aren't just descriptions of the architecture, they are **rules that subagents and developers can check code against**.

#### Document Types

**1. Architecture Compliance Document**
When to produce: When establishing or updating codebase guardrails.
Save to: `.claude/architecture.md` or `docs/architecture/compliance.md`

This is the primary document subagents read before writing code. It must be:
- Specific enough that a subagent can check its own work against it
- Organized by concern (boundaries, dependencies, patterns, testing)
- Written as rules, not descriptions

Template:
```
# Architecture Compliance Rules

## System Overview
[1-2 sentences: what this system does and its architecture style]

## Boundary Rules
### Module Boundaries
- List of modules/bounded contexts with their responsibilities
- What each module owns (entities, tables, APIs)

### Dependency Direction
- Which modules may depend on which
- Forbidden dependency paths (e.g., "domain/ must never import from infrastructure/")
- How cross-module communication works (events, interfaces, shared contracts)

### Layer Rules
- Layer definitions with allowed/forbidden imports per layer
- Example: "use_cases/ may import from domain/ but never from infrastructure/"
- Example: "api/ may import from use_cases/ but never from domain/ directly"

## SOLID Compliance
### SRP Checks
- Maximum responsibilities per class/module
- Signs of violation to watch for
- Specific classes that are at risk

### DIP Checks
- All external services must be accessed through interfaces defined in domain/
- List of abstraction boundaries (e.g., "Database access: Repository interfaces")
- Concrete implementations must live in infrastructure/

### OCP Checks
- Extension points and how to extend them
- Things that must not be modified (only extended)

## Pattern Rules
### Required Patterns
- Where specific patterns must be used (e.g., "All payment processing uses Strategy pattern")
- Why each pattern is required

### Forbidden Patterns
- Anti-patterns that must not appear
- Example: "No God classes (max 3 public methods per class in domain/)"
- Example: "No direct database queries outside infrastructure/"

## Testing Requirements
### Unit Test Rules
- Domain entities: Pure tests, no mocks, no I/O
- Use cases: Mock all interfaces, test business logic only
- Minimum: Every public method in domain/ and use_cases/ must have tests

### Integration Test Rules
- Infrastructure adapters: Test against real services (test instances)
- Boundary contracts: Verify interface implementations match contracts

### What Must Be Testable Without Infrastructure
- All business rules
- All validation logic
- All use case orchestration

## File/Directory Conventions
### Structure
[Show the required directory layout]

### Naming Conventions
- Files, classes, interfaces, tests

### Where Things Go
- New entities: domain/entities/
- New use cases: use_cases/
- New external integrations: infrastructure/
- New API endpoints: api/
```

**3. Boundary Map**
When to produce: When the system has multiple modules, services, or contexts.
Visual and textual representation of what talks to what.

Template:
```
# Boundary Map

## Contexts
[List each bounded context with its core responsibility]

## Dependency Graph
[ASCII or mermaid diagram showing allowed dependencies]

## Communication Contracts
### [Context A] → [Context B]
- Method: [direct call | event | API | message queue]
- Contract: [interface name or event schema]
- Data exchanged: [DTOs or event payloads]

## Forbidden Dependencies
[Explicit list of dependency paths that must never exist]
```

**4. Coding Standards Document**
When to produce: When establishing team conventions or agent guardrails.
Save to: `.claude/coding-standards.md`

Focus on architecture-relevant standards (not formatting). This tells a subagent how to write code that fits this codebase.

Template:
```
# Coding Standards

## Architecture Alignment
- How to add a new feature (which files to create, in which order)
- How to add a new external integration (create interface first, then implementation)
- How to add a new API endpoint (wire through use case, never call domain directly)

## Dependency Rules
- Import restrictions by layer
- How to declare and resolve dependencies (DI container, constructor injection, etc.)

## Error Handling Strategy
- Where errors are caught vs propagated
- Domain errors vs infrastructure errors
- Error response format

## Naming and Organisation
- File naming by type (entity, use case, repository, controller)
- Interface naming convention (e.g., prefix with I, or suffix with Repository/Service)
- Test file naming and location

## Review Checklist
A subagent or reviewer should check:
□ New code respects layer boundaries
□ No new direct dependencies on frameworks in domain/
□ Interfaces defined for any new external service
□ Unit tests cover business logic without infrastructure
□ No circular dependencies introduced
```

#### Documentation Workflow Steps

1. **Determine document type** based on request:
   - "Document the architecture" or "write architecture docs" → Full compliance document + boundary map
   - "Create coding standards" or "guardrails" → Coding standards document
   - "Strategy for [codebase]" → Compliance document tailored to specific codebase

2. **Gather context**:
   - If codebase exists: scan it first (use Workflow 2's scan step)
   - If designing from scratch: use output from Workflow 1
   - If updating existing docs: read current docs first, identify gaps

3. **Produce the document**:
   - Use the appropriate template above
   - Fill in with specific, checkable rules (not vague guidance)
   - Reference architecture principles by code (SRP, DIP, etc.)
   - Include concrete examples from the actual codebase where possible

4. **Validate the document**:
   - Every MUST/MUST NOT rule should be verifiable by reading code
   - Every boundary rule should name specific directories or modules
   - Every pattern rule should include when to apply and when not to
   - A subagent reading only this document should know where to put new code

## Reference Documents

Three reference books are embedded in `references/`. Read the relevant file when you need principle definitions, pattern details, or architecture style trade-offs:

- **`references/clean-architecture.md`** — SOLID principles, component principles, Clean Architecture pattern, boundaries, testability.
- **`references/design-patterns.md`** — All 23 GoF patterns with intent, when to use, and architecture relevance.
- **`references/fundamentals-of-software-architecture.md`** — Architecture characteristics, all styles with ratings, choosing a style, ADRs, risk analysis.

## Output Guidelines

**For design work**:
- Start with high-level structure (boundaries, layers)
- Show dependency directions with arrows
- Explain why this structure supports testability and extensibility
- Identify extension points for future features
- Note key trade-offs

**For audit work**:
- Be specific — cite files, line numbers, class names
- Explain the principle violation clearly
- Show the refactoring path (before → after)
- Prioritize by impact to testability and extensibility

**Always**:
- Keep business logic isolated from frameworks
- Make the architecture scream the domain (entities and use cases visible)
- Ensure high-level policy doesn't depend on low-level details
- Design for testability (can you test business rules without database/UI/framework?)
