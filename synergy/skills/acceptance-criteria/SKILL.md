---
name: acceptance-criteria
description: 'Write test steps a tester or stakeholder can follow in the UI for a PR or feature branch. Trigger on acceptance criteria, test steps or "what should I test".'
---
# Acceptance Criteria Skill

Produces a short smoke check for a feature or PR: the minimum a tester does to see the change working. The audience is testers and stakeholders who interact with the product through the UI, not developers reading code.

This is not a test plan. It does not try to cover everything that could be tested. A tester who has run it knows whether the change did what it said, and nothing more.

Read `_shared/wording-standard.md` and `_shared/banned-patterns.md` before writing. Both apply to acceptance criteria. Write each step in plain language a tester who is not involved in this codebase can follow, and explain what a feature does rather than naming internal identifiers.

`skills/user-facing-communication/SKILL.md` shapes what you say to the person **around** the criteria: lead with the outcome and the current state, keep it short, and surface anything outstanding or assumed. It governs your reply, not the criteria itself.

---

## Process

1. Read the change and group it by what a user would notice, following `_shared/reading-changes.md`. It covers a branch (the default), a pull request number, or pasted notes.
2. Keep the user-facing groups and drop the internal-only ones.
3. Fold or drop the knock-on groups. A group that only keeps something looking or working as it did before, because of the main change, is not its own bullet. Fold it into the main bullet if a tester would miss it, otherwise drop it.
4. For each group that is left, write the one check that shows the change working, then stop. If the change comes in two variants a person sees (light and dark mode, signed in and signed out), add one more step for the other variant.

---

## Output Format

Return acceptance criteria inside a single fenced code block so the user can copy/paste directly.

Each change group is one bullet with sub-bullets for test steps:

```
* Fixed [what changed] so that [why/what it enables]. Test the following:
   * [Test step 1]
   * [Test step 2]
```

---

## Writing Rules

- **Lead bullet**: One sentence. Starts with a bold past-tense verb (**Updated**, **Added**, **Fixed**, **Removed**, **Changed**). States what changed and why in plain language. Ends with "Test the following:"
- **Sub-bullets**: Each is one thing to do and confirm, written for someone using the product, not reading the code. Two is the usual number and three is the most.
- **Basic functionality only.** Test that the change does the thing it set out to do. Do not test what already worked before the change, such as tapping back to go to the previous screen, or what only varies by route to the same screen, such as opening it from a list.
- **Examples, not coverage.** When a change reaches many screens or records, name a few as examples ("for example Count, Place Order and Log Delivery") and ask the tester to try several. Never list each one, and never ask for the same check on every screen.
- **No edge cases.** Leave out empty states, error paths, rapid repeats and combinations, unless one of them is the whole point of the change.
- **Group by user-facing change**, not by file or module. Multiple code changes that produce one visible behavior change are a single bullet.
- **Skip purely internal changes** that have no user-facing or testable impact (refactors, renames, test-only changes, .gitignore updates).
- Keep the total output short. One bullet is the usual answer, and three is the most, even for a large PR. If the PR changes more than three things a person would notice, keep the three that matter most and say in your reply which you left out.
- No em dashes. Use commas, periods, or parentheses instead.
- No code identifiers (class names, method names, field paths) unless the user directly interacts with them in a config editor or similar.
- No developer jargon. Write for someone who knows the product but not the codebase.

---

## Examples

### Example 1: A fix that reaches many screens

```
* Fixed the back button arrow being invisible in light mode, which also made screen titles look shifted to the right. Test the following:
   * In light mode, open several Inventory screens that have a back button (for example Count, Count Summary, Place Order, Log Delivery and Supplier Item Codes) and confirm a dark arrow shows at the top left of each one
   * Switch to dark mode, repeat a few of the screens above, and confirm the arrow is still visible (light on the dark background)
```

The same PR also kept the arrow white on one red header so it stays visible. That is a knock-on of the fix, so it has no bullet of its own.

### Example 2: New UI filter

```
* Added a date range filter to the audit report page. Test the following:
   * Select a start and end date and confirm the report filters to that range
   * Clear the filter and confirm all records reappear
```

A range with no data is an edge case, so it is left out.

### Example 3: Bug fix

```
* Fixed scheduled scripts creating duplicate tenant tracker entries when run concurrently. Test the following:
   * Run the same script twice in quick succession and confirm only one tracker entry is created
```

### Example 4: Two separate changes in one PR

```
* Updated the notification email to include the client name in the subject line. Test the following:
   * Trigger a notification and confirm the email subject contains the client name
* Fixed the data slicer crashing when the target field is null. Test the following:
   * Run a data slicer with a null target field and confirm it completes without error
```
