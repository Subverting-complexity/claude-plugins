---
name: grill
description: 'Interview the user hard about a plan until every open question is answered or deferred. Trigger on "grill me", "stress-test this" or "poke holes in this".'
---
# Grill

Question a plan until its weak points are found and each open question has an answer or has been parked on purpose. The interview is worth running only if it changes something: a session in which the user agrees with everything and never has to stop and think has not found the parts of the plan nobody has decided yet.

This skill is the one interview procedure in this plugin. Run it directly to stress-test a plan, or let `feature-discovery` run it as its interview. When another skill runs it, that skill supplies the subject and a list of topics that must be covered before the grill closes; everything about how the questions are asked lives here.

## Output standard

Everything a person reads — plans, questions, findings, summaries, and anything posted or committed — follows `skills/_shared/wording-standard.md` for how it reads, `skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `skills/_shared/banned-patterns.md` for what must never appear. Every reply, not only the last one.

## No person present

A grill needs somebody to answer it. When nobody is there, because the session is an agent run, a scheduled routine, or a subagent, do not answer the questions yourself and do not carry on as if a guess were a decision.

1. Do the research and the mapping below as normal.
2. Write down every question you would have asked, each with your recommendation and why, grouped by topic.
3. Put that record where the next person will see it, and stop. When the subject is a GitHub issue: post the questions as a comment on it (written to the `writing-github-issues` standard and `_shared/body-standard.md`), then set its `Stage` to `Needs refinement` so no code agent picks it up before a person has answered: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" stage-set {number} --stage stage-refinement`. When there is no issue, the record is the reply that ends the session.

A calling skill that is itself running unattended inherits this rule: it stops at the same point and reports the open questions rather than producing stories from guesses.

## How a grill runs

1. **Get the plan.** If the user has not described it yet, ask them to, in one plain-text question with no options.
2. **Look before asking.** Read what can answer questions without the user: the codebase, the README and project docs, the issue and its comments, anything they linked. See **Checking the sources first**.
3. **Find where it will break.** Before the first question, decide which parts of this plan are most likely to fail or have not really been decided. Use **Where to push** as the checklist. Those are the first batch.
4. **Question in batches.** Hardest topic first, each batch as large as the questions allow. See **Pacing**.
5. **Keep a record.** Track privately what has been settled, what was deferred and why, and which answers conflict. Do not show this record while the interview is running.
6. **Check coverage.** When a calling skill supplied topics that must be covered, go through them now and question any that are still open. Topics the research already answered count as covered.
7. **Sweep for what is still shaky, and go again.** See **Until nothing is shaky**. Steps 4 to 7 repeat until a sweep finds nothing.
8. **Close.** See **Closing**.

## Where to push

Questions about preferences are cheap to answer and reveal little. Questions about consequences find the gaps. Before each batch, pick the items below this plan has not yet been tested against, and skip the ones that do not apply to it.

- **How it fails.** When this breaks in production, who finds out, how, and what do they do next? A plan with no answer has only been pictured working.
- **What it rests on.** Name the thing the plan assumes but nobody has checked, and ask what happens if it turns out to be false.
- **What was left out rather than decided.** Vague phrasing, passive voice and "we'll just" usually mark a part nobody has decided. Ask about it directly.
- **The awkward user.** Someone with bad input, out-of-date data, the wrong permissions, or the same thing open twice. Plans are usually drawn for the user who does everything right.
- **The boundary.** What is this deliberately not doing? Scope with no stated edge grows during the build.
- **Decisions that cannot be undone.** Separate the choices that are cheap to reverse from those that are not. Spend the interview on the second kind and settle the first kind quickly.
- **What it replaces.** If something already exists, what happens to it, the data it holds and the people relying on it today?
- **Success at scale.** If usage is ten times what is expected, what gives way first?

## Pacing

A grill should move quickly. Most slow interviews are slow because they ask one small question at a time.

- **Ask everything that is ready, in one turn.** Every question on the topic goes together, and questions on other topics join the batch when their answers do not depend on each other. Five to ten questions in a turn is fine when the plan has that many open points. There is no cap of four.
- **Hold back only what depends on the batch.** A question whose wording, or whose point, changes with an answer in this batch waits for the next turn.
- **Hardest first.** A foundational answer that changes can make later questions pointless, so find it early.
- **Push on a vague answer.** "It depends", "probably", and "we'll work that out" are not answers. Ask again with a sharper version of the question, and keep going until the answer is concrete or the user chooses to defer it and says why. Record a deferral with that reason; never skip a question silently.
- **Let a settled answer go.** When an answer is clear and holds up, acknowledge it briefly and move on. Do not repeat it back.
- **Drop questions an answer has made moot.** Mention it only if the user would otherwise wonder where the question went.
- **Raise a conflict in the same turn.** When an answer contradicts an earlier one, say so immediately and ask which stands.

## Asking a question

**Lead with a recommendation.** Every question states what you would choose and why, then asks whether the user agrees. A bare question leaves all the thinking to the user and hides where you think the risk is.

**Write for a reader with no context.** Follow `_shared/wording-standard.md` for every question, recommendation and option. The person answering may not have seen the reasoning behind the question, so state the problem and the proposed answer in full sentences, give the reason in plain language, and define jargon while keeping identifiers in backticks.

Hard to follow without context:

> Cache layer? Redis vs in-mem LRU, TTL 5m, invalidate on write.

Easy to follow:

> - **The problem:** Product lookups hit the database on every request, and the catalogue page makes dozens of them per load.
> - **Recommendation:** Add a read-through cache in front of `ProductRepository`, using the existing Redis instance rather than an in-memory `LRU` cache so every server instance shares it. Entries expire after 5 minutes, and an entry is cleared when its product is updated. Do you agree, or would you prefer a different store or expiry?

### Use `AskUserQuestion`

Every question with a bounded set of answers goes through the `AskUserQuestion` tool, not plain text: yes or no, choosing between approaches, confirming a recommendation, in or out of scope.

- 2 to 4 options per question, with short labels.
- The recommended option comes first, with "(Recommended)" at the end of its label.
- The tool takes at most 4 questions in one call. That is the limit of a call, not of a batch: a larger batch goes as several calls, one straight after the other with no reply between them, with the questions grouped by topic.
- Each label and description carries the problem and the proposed answer on its own, because it is often all the reader sees.
- The tool always offers "Other". If you want to add your own "Other" option, the question is open and belongs in plain text.
- A chosen option is the recorded decision unless it needs probing.

Plain text is only for three cases: the opening request to describe the plan, following up a vague answer (which needs the user's own words), and a question whose answer genuinely cannot be reduced to a few options.

## Checking the sources first

Never ask for anything the user would need to look up. Their time in the interview is for what only they know, which is what they intend.

When a source answers a question:

- Show what you found: the file or document, and the relevant detail, briefly.
- Say what you are recording because of it.
- Move on.

Never settle a question silently from a source. Give the user room to point out that the code is about to change.

## Until nothing is shaky

One pass over the hard topics does not finish a grill. Answers open new questions, and a decision that sounded firm alone can be weak beside the others. After each round of batches, sweep the plan again:

1. **Read the record as a whole and list every point that would still worry you if you owned this plan.** Look for an answer that was accepted but is thin, a decision that rests on something nobody checked, two decisions that hold together only if a third thing is true, a consequence of an answer that nobody followed, an item in **Where to push** that applies and was not tested, and a deferral whose reason a later answer has removed.
2. **Check the sources** for each point first, as in **Checking the sources first**.
3. **Ask the rest as the next batch**, and say in one line that this is a further round on what is still weak.
4. **Sweep again.** The grill is finished when a sweep finds nothing.

A point leaves the list in one of three ways only: the user gives a concrete answer that holds up, a source settles it and the user has seen that, or the user chooses to leave it and says why. A point never leaves because the interview has run long or because the user sounded confident. There is no fixed number of rounds.

Do not invent worries to keep the interview going. A choice that is cheap to reverse, or that changes nothing whichever way it goes, is not shaky: state what you will assume, in one line, and move on unless the user objects.

The user can stop at any time. Close then, and list every point the sweep had not cleared under **Still shaky**.

## Closing

Propose closing when a sweep finds nothing: every question is answered or deferred with a reason, nothing still open blocks the next step, and any coverage list from a calling skill is complete.

End with a brief recap, in the conversation itself, readable in under a minute. Do not write a file or a document.

- **Decided:** the decisions, a line each.
- **Open:** each deferred question and the reason it was deferred.
- **Still shaky:** each point the sweep had not cleared when the user stopped the interview, and what it puts at risk. Say it plainly. After a grill that ran to the end this is empty, because a point the user chose to leave is under **Open**; write "nothing" then, and do not add a worry you never raised in the interview.

When a calling skill ran the grill, the recap hands control back to it and its next phase starts from these decisions.
