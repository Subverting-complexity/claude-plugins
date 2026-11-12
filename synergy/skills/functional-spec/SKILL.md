---
name: functional-spec
description: 'Write a functional spec for a feature or change: an overview, then the behaviour as short rules, with no technical design. Trigger on "functional spec", "spec this" or "write the spec". Not for user stories.'
---
# Functional spec

This skill writes a functional spec: what a feature does for its users, and the rules it follows. A business reader, a tester and a developer read the same spec and agree on what the system must do. The spec does not say how to build it. The team adds the technical design later.

`skills/user-facing-communication/SKILL.md` shapes what you say to the person around the spec: lead with the spec and its current state, keep it short, and surface open points and assumptions. It governs your reply, not the spec.

The spec follows `_shared/wording-standard.md` and `_shared/banned-patterns.md`. When it goes into a tracker, it is a tracker body, so `_shared/body-standard.md` applies too: each paragraph and each bullet on one unwrapped line.

A user story with an Overview and a Technical section is the `user-story` skill. Test steps are the `acceptance-criteria` skill. A check of a finished spec against the code is the `spec-hardening` skill.

## Process

1. **Read the sources.** Read the notes, the chat, the decisions, the issue and the mock-up in full. If the feature changes an existing product, read the code that does the job today, so the spec uses the product's own words and states what does not change.
2. **Settle the open points.** Settle every point that the sources answer. If points are still open, ask about them in 1 batch, with the option you suggest for each. Only when the person wants to explore an idea that nobody has decided, run `skills/grill/SKILL.md` first.
3. **Write the spec** in the shape below.
4. **Check the spec** against the checklist below once, and fix what you find. If a mock-up exists, check both ways: each screen, control and rule in the mock-up is in the spec, and each rule in the spec is in the mock-up.
5. **Hand over.** Give the spec, then list the open points and assumptions in your reply, not in the spec. If the person asks you to put it into a tracker, write it in that tracker's format, and show the change before you make it.

## Shape

- **Title.** `<Area>: <Feature>`, in title case, such as `Orders: Bulk Cancel with Undo`.
- **Overview.** The first section, as in a user story: 1-2 short paragraphs of prose. Say what the feature lets users do, who benefits and why it matters now, including what does not work today. Name the event that showed the problem, if there was one. If a mock-up is attached, say so in 1 sentence. Do not split it into a Problem and a Goal section.
- **1 section for each part of the behaviour.** Name each section after the concept, such as `Versions`, `Choosing a version` or `Undo`. Give each screen its own section, such as `Admin page: Order History`, and each flow too, such as `Bulk cancel`. Order the sections as a reader meets the feature.
- **Bullets inside each section.** 1 rule in each bullet. Use a nested list for a set of conditions or results, such as "when all of these are true".

Add a section only when it is relevant to this feature. The list of rules below says what to cover when it applies, not a section to fill in each spec: approval, records, what does not change and what does not happen get a section of their own only when the feature changes them or a reader could expect otherwise. A short spec with 2-3 sections is normal. Leave out sections that carry nothing. Do not add an overview, a technical section, acceptance criteria, an open questions section, an out of scope section, or a status, date or author line, unless the person asks.

## How to write the rules

- **Say what the user and the system do,** never how it is built. No tables, classes, endpoints, packages, file paths or migrations.
- **Give an example** for each name, format and number, such as "a name with the version and a date, for example Python 3.12 (2026-11)".
- **Say how firm each number is.** A fixed limit and a guideline read the same unless you say which: "This is a guideline, not a fixed schedule."
- **Say what does not happen,** when a reader could expect it: no email is sent, the failed run is not run again, nothing moves automatically.
- **Say what does not change:** permissions, other screens and existing settings that the feature leaves as they are.
- **Say who can do each action,** and where in the product they do it.
- **Name the default and the most specific rule,** when a setting can be made at more than 1 level.
- **Keep the person's own limits,** such as "must stay easy to build", when they stated them.
- **Name related work items** by their number and title, with a hash before the number, such as `#36032 — Pipeline monitor on action failure`, so that Azure DevOps and GitHub link it.

## Checklist

- The overview makes sense to a reader who has not seen the chat.
- Each rule is testable: a tester can say if the system follows it.
- Each rule appears once. 2 rules do not contradict each other.
- Each screen, flow and state that the person agreed has a section or a bullet.
- No rule describes the technical design.
- No decision appears that the person did not make. An open point is in the reply, not in the spec.
- If a mock-up exists, the spec and the mock-up match both ways.
