<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->
# Story Template

Each story is a single-session unit of work for an autonomous agent.
Use the 12-section issue template, omitting sections that don't apply:

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
