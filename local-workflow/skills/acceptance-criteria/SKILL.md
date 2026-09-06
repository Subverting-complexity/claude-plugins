---
name: acceptance-criteria
description: "Write user-facing acceptance criteria — test/QA steps — for a PR or feature branch, aimed at testers and stakeholders using the UI. Use when the user wants AC, test steps, or 'what should I test' for a feature or PR. Do NOT use for writing user stories (use user-story) or reviewing code quality (use code-review)."
---
<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->

# Acceptance Criteria Skill

Produces short, user-facing acceptance criteria for testing a feature or PR. The audience is testers and stakeholders who interact with the product through the UI, not developers reading code.

Read `_shared/wording-standard.md` and `_shared/banned-patterns.md` before writing. Both apply to acceptance criteria. Write each step in plain language a tester who is not involved in this codebase can follow, and explain what a feature does rather than naming internal identifiers.

`skills/user-facing-communication/SKILL.md` shapes what you say to the person **around** the criteria: lead with the outcome and the current state, keep it short, and surface anything outstanding or assumed. It governs your reply, not the criteria itself.

---

## Process

1. Read the branch diff (`git diff master...HEAD`) and commit history to understand what changed
2. Identify the user-facing impacts of the changes
3. Write acceptance criteria focused on what a tester can verify through the UI or system behavior

---

## Output Format

Return acceptance criteria inside a single fenced code block so the user can copy/paste directly.

Each change group is one bullet with sub-bullets for test steps:

```
* Updated [what changed] so that [why/what it enables]. Test the following:
   * [Test step or verification 1]
   * [Test step or verification 2]
   * [Test step or verification 3]
```

---

## Writing Rules

- **Lead bullet**: One sentence. Starts with a bold past-tense verb (**Updated**, **Added**, **Fixed**, **Removed**, **Changed**). States what changed and why in plain language. Ends with "Test the following:"
- **Sub-bullets**: Each is a specific thing to do or verify. Written for someone using the product, not reading the code.
- **Group by user-facing change**, not by file or module. Multiple code changes that produce one visible behavior change should be a single bullet.
- **Skip purely internal changes** that have no user-facing or testable impact (refactors, renames, test-only changes, .gitignore updates).
- Keep the total output short. Aim for 2-5 top-level bullets. If the PR only does one thing, one bullet is fine.
- No em dashes. Use commas, periods, or parentheses instead.
- No code identifiers (class names, method names, field paths) unless the user directly interacts with them in a config editor or similar.
- No developer jargon. Write for someone who knows the product but not the codebase.

---

## Examples

### Example 1: Resilient work item creation

```
* Updated DevOps work item creation to be phased so that missing or invalid custom fields no longer block work item creation. Test the following:
   * Send a support request and ensure all fields (tags, priority, category, client name) populate as expected
   * Send a support request for a tenant whose name isn't in the Client Name picklist. Work item should still be created with a comment noting the field couldn't be set
   * Send a follow-up email on an existing thread and confirm the support request summary, urgency, and category update correctly
   * Use the chatbot agent to create a DevOps work item and confirm all fields populate correctly
```

### Example 2: New UI filter

```
* Added a date range filter to the audit report page. Test the following:
   * Select a start and end date and confirm the report filters to that range
   * Clear the filter and confirm all records reappear
   * Select a range with no data and confirm an empty state message displays
```

### Example 3: Bug fix

```
* Fixed scheduled scripts creating duplicate tenant tracker entries when run concurrently. Test the following:
   * Trigger a scheduled script and confirm only one tracker entry is created
   * Run the same script twice in quick succession and confirm no duplicates appear
```

### Example 4: Multiple changes in one PR

```
* Updated the notification email to include the client name in the subject line. Test the following:
   * Trigger a notification and confirm the email subject contains the client name
   * Trigger a notification for a tenant with no client name configured and confirm the email still sends with a fallback subject
* Fixed the data slicer crashing when the target field is null. Test the following:
   * Run a data slicer with a null target field and confirm it completes without error
   * Run a data slicer with a valid target field and confirm results are unchanged
```
