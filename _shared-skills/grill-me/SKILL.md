---
name: grill-me
description: "Interview the user relentlessly about a plan or design until reaching shared understanding, resolving every open question. Use this skill whenever the user wants to stress-test a plan, get grilled on their design, or says anything like \"grill me\", \"stress-test this\", \"challenge my thinking\", \"poke holes in this\", \"walk me through the decisions\", or \"interview me about this\". Also trigger when the user shares a plan, architecture, feature design, or technical approach and wants it interrogated rather than just reviewed. If a codebase is available, explore it instead of asking when the answer can be found there. Do NOT use for code-specific feature planning or backlog work (use feature-discovery for that). Do NOT use for reviewing code changes (use code-review instead)."
disable-model-invocation: true
---

# Grill Me

Relentlessly interview the user about their plan or design until every open question is resolved. For each question, provide your recommended answer before the user responds.

## How It Works

1. **Open** — Ask the user to briefly describe the plan or design if they haven't already.
2. **Interview** — Work through every open question:
   - Batch related questions together using `AskUserQuestion` with
     up to 4 questions per call.
   - Lead with your recommended answer as the first option.
   - Wait for the user's responses before moving to the next batch.
   - If the codebase can answer a question, explore it instead of
     asking, then show what you found and state the decision you're
     recording.
3. **Track** — Maintain a running internal record of resolved decisions
   as you go (not shown to user during interview).
4. **Close** — When all questions have a resolved answer or a conscious
   deferral, present a summary of all decisions in the conversation.
   Do not write any files.

## Interview Discipline

- **Batch related questions.** Group questions on the same topic into
  one `AskUserQuestion` call (up to 4 questions per call). Don't
  artificially slow the interview by asking one thing at a time.
- **Lead with recommendations.** Your recommended answer should be the
  first option in the list with "(Recommended)" appended to the label.
- **Use `AskUserQuestion`** when a question has a finite set of clear
  choices (2-4 options). The user can always select "Other" to type a
  custom answer. Fall back to plain text for open-ended questions
  where the answer space is too wide for options.
- **Explore before asking.** If a codebase is present, check it first.
  Show what you found, state the decision being recorded, and continue.
- **Push back on vague answers.** If the user says "it depends" or
  "probably X", probe until the answer is concrete or explicitly
  deferred.
- **Flag conflicts.** If a later answer contradicts an earlier decision,
  surface it immediately.
- **Defer consciously.** If something genuinely can't be decided yet,
  mark it as an open issue and move on.

## Codebase Exploration

When a codebase is available and a question can be answered by reading it:
- Explore using available tools (file reads, search, bash).
- Show a brief summary of what you found (file name, relevant snippet
  or finding).
- State the decision you're recording based on that finding.
- Continue to the next question.

Do not silently resolve. Always show the user what was found.

## Output

Present all decisions as a summary in the conversation when the
interview is complete. Do **not** write decision documents to the
filesystem. The conversation is the record.

## Completion Signal

Propose closure when:
- All major questions have a resolved answer or a conscious deferral
- No open questions remain that would block the next step
