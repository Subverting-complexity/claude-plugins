---
name: grill-me
description: "Interview the user relentlessly about a plan or design until reaching shared understanding, resolving every open question. Use this skill whenever the user wants to stress-test a plan, get grilled on their design, or says anything like \"grill me\", \"stress-test this\", \"challenge my thinking\", \"poke holes in this\", \"walk me through the decisions\", or \"interview me about this\". Also trigger when the user shares a plan, architecture, feature design, or technical approach and wants it interrogated rather than just reviewed. If a codebase is available, explore it instead of asking when the answer can be found there. Do NOT use for code-specific feature planning or backlog work (use feature-discovery for that). Do NOT use for reviewing code changes (use code-review instead)."
---

# Grill Me

Relentlessly interview the user about their plan or design until every open question is resolved. For each question, provide your recommended answer before the user responds.

## How It Works

1. **Open** — Ask the user to briefly describe the plan or design if they haven't already.
2. **Interview** — Work through every open question:
   - Batch related questions together. Group questions that belong to the same topic into a single turn.
   - Lead with your recommended answer for each question.
   - Wait for the user's responses before moving to the next batch.
   - If the codebase can answer a question, explore it instead of asking, then show what you found and state the decision you're recording.
3. **Track** — Maintain a running internal record of resolved decisions as you go (not shown to user during interview).
4. **Close** — When all questions have a resolved answer or a conscious deferral, propose closure: "I think we've covered everything. Want to wrap up and generate the decision doc?"
5. **Output** — On user confirmation, produce the decision document (see format below).

## Interview Discipline

- **Batch related questions.** Group questions on the same topic into one turn. Use multiple `interactive selection` calls per turn when they cover related decisions. Don't artificially slow the interview by asking one thing at a time.
- **Lead with recommendations.** Don't just ask. Give your best answer, then ask if the user agrees or wants to change it.
- **Use tappable options** when a question has a finite set of clear choices (see Tappable Options section). Fall back to plain text for open-ended or context-heavy questions.
- **Explore before asking.** If a codebase is present, check it first. Show what you found, state the decision being recorded, and continue.
- **Push back on vague answers.** If the user says "it depends" or "probably X", probe until the answer is concrete or explicitly deferred.
- **Flag conflicts.** If a later answer contradicts an earlier decision, surface it immediately.
- **Defer consciously.** If something genuinely can't be decided yet, mark it as an open issue and move on.

## Tappable Options (Interactive Elicitation)

When `interactive selection` is available, use it for questions with a small set of distinct, reasonable answers. Your recommendation still leads the question in the conversational text before the options appear, and one of the options should reflect that recommendation.

### When NOT to use tappable options

Skip them for questions that need freeform answers: the opening question ("describe the plan"), probes into vague answers, and questions where the answer space is too wide. If you find yourself writing an "Other" option because the real answer probably isn't in the list, just ask in plain text.

### Format guidance

- 2-4 options per question, short labels.
- After the user taps an option, acknowledge their choice briefly and move on. The selected option becomes the recorded decision unless you need to probe further.
- If the user's answer conflicts with an earlier decision, surface the conflict before continuing.

## Codebase Exploration

When a codebase is available and a question can be answered by reading it:
- Explore using available tools (file reads, search, bash).
- Show a brief summary of what you found (file name, relevant snippet or finding).
- State the decision you're recording based on that finding.
- Continue to the next question.

Do not silently resolve. Always show the user what was found.

## Output Format

Produce a markdown document at the end of the interview.

Write to `.decisions/<plan-name>-<YYYY-MM-DD>.md` relative to the current
working directory. Create the `.decisions/` directory if it doesn't exist.
Confirm the path to the user after writing.

---

### Document Structure

```markdown
# [Plan or Design Name] — Decision Record
_Generated: YYYY-MM-DD_

## Summary
One paragraph. What is being built or decided, and what was the outcome of the interview.

## Decisions

### [Topic Area]
**Decision:** [What was decided]
**Rationale:** [Why, drawn from the conversation]
**Alternatives considered:** [If any came up]

### [Next Topic Area]
...

## Open Issues
- [Any decision explicitly deferred, with the reason]

## Assumptions
- [Things treated as true that weren't explicitly verified]
```

Use as many decision sections as needed. Group related decisions under a shared heading. Keep each entry tight: one decision, one rationale, done.

---

## Completion Signal

Propose closure when:
- All major questions have a resolved answer or a conscious deferral
- No open questions remain that would block the next step

Wait for confirmation before producing the document.
