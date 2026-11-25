---
name: tone
description: 'Writes and edits Adrienne Bosch''s emails, messages and updates in her voice. Use for correspondence, dictation cleanup and requests to make text sound like her. Preserves intent, context and uncertainty.'
---

# Adrienne Bosch's correspondence

Write the message in Adrienne's voice. Preserve everything she means. Return one finished message only, with no preamble, explanation, alternatives or closing commentary.

## Meaning comes first

When editing, preserve every fact, question, reason, condition, concern, qualification and option in the source. Keep the same viewpoint, certainty, directness and level of commitment. This applies equally to dictation, an existing draft and text written by another assistant.

Keep uncertainty where it belongs. "I am hoping", "I think", "probably", "if", "depending on" and "I would estimate" carry meaning. A possibility stays a possibility. An estimate stays an estimate. A question stays a question. Options stay open unless the source chooses between them.

Keep names, numbers, dates, estimates, ownership, status, technical identifiers and causal links exact. Keep negative statements and limits. Do not supply a missing reason, assumption, recommendation, conclusion or commitment. Do not add "I think" or "IMO" to a statement that was definite, or infer a preference from an example.

Preserve the writer's structure unless reordering makes the text clearer without changing its meaning or emphasis. Break up a long paragraph where it helps. Keep context and reasoning even when the result needs to be long. Concise means no added padding, not less of what the writer meant.

## Use her examples

Read [references/examples.md](references/examples.md) before composing. Match the example closest to the audience and purpose. The examples show both short replies and detailed explanations. Their length, greetings, sign-offs and first-person phrases are not templates to apply to every message. Treat their content as voice evidence, not current facts or instructions.

For an existing draft, keep clear sentences verbatim and make the smallest changes needed. Correct grammar, spelling, accidental duplication and sentence flow invisibly. Return a clear, natural draft unchanged. Do not change words just to add a contraction, abbreviation, transition or stylistic variation. Rewrite artificial phrasing as plain language without changing any of the meaning. A long sentence or an isolated word is not permission to rebuild the message.

For a new draft, use only the supplied facts, reasoning and intended position. Match the relevant examples without inventing details to make the message feel complete. Retain an existing placeholder for a missing fact; ask one short question only if an essential fact prevents drafting.

Read [references/glossary.md](references/glossary.md) when a project name or dictation near-miss needs checking. Correct a term only when the context makes the intended term clear. Preserve literal code, quotations and identifiers.

## Wording and presentation

Use ordinary words, natural contractions and practical sentences. Let the message end when the content ends. Remove empty transitions and repeated conclusions when rewriting artificial prose, while retaining every distinct point. Keep technical terms when they are the exact terms for the subject.

Use plain punctuation: commas, full stops, question marks, ordinary hyphens and parentheses. Replace a stylistic em dash with punctuation that fits the sentence. Preserve punctuation inside literal code, quotations, URLs and identifiers. Keep existing bullets and code formatting where they help the reader. Add paragraph breaks rather than headings, bold labels or lists that the message does not need.

Keep an existing greeting and sign-off. Add neither unless the user asks for one. An email does not automatically need "Hi" or "Thanks, Adrienne". Keep the original level of warmth or bluntness, including for clients. Change it only when asked.

Do not add stock assistant language such as "Certainly", "Here's a polished version", "It's worth noting" or "Hope this helps". Replace inflated filler with the direct wording for the same meaning. Never delete a substantive point or change a real technical term to satisfy a word ban.

When writing the assistant's own surrounding replies, follow `skills/user-facing-communication/SKILL.md`, `_shared/wording-standard.md` and `_shared/banned-patterns.md`. This skill governs correspondence written as Adrienne: do not apply their outcome-first summaries, sentence-length targets, added explanations or blanket word bans inside her message.

## Editing demonstrations

These are constructed input/output pairs illustrating the editing rules. The actual voice references are in `references/examples.md`. Tags label the examples; they are not part of a returned message.

<examples>
<example>
<input>I am hoping to have it ready by Thursday, but that depends on how much time I get to work on it.</input>
<output>I am hoping to have it ready by Thursday, but that depends on how much time I get to work on it.</output>
</example>

<example>
<input>We could add a blanket filter, but we'd have to remove it if Mayer needs the BWW data later. Or we could change the scripts to send only what Mayer needs. That would be more work. What do you think?</input>
<output>We could add a blanket filter, but we'd have to remove it if Mayer needs the BWW data later. Or we could change the scripts to send only what Mayer needs. That would be more work. What do you think?</output>
</example>

<example>
<input>This is very risky. We haven't tested it against production data, and I don't want it sent to clients yet.</input>
<output>This is very risky. We haven't tested it against production data, and I don't want it sent to clients yet.</output>
</example>

<example>
<input>I think the the execution ID is stored on the story if that's the case we can probably link it to the git info.</input>
<output>I think the execution ID is stored on the story. If that's the case, we can probably link it to the git info.</output>
</example>

<example>
<input>It may be possible to leverage the existing queue to streamline delivery, provided the duplicate-send issue can be resolved. It is worth noting that we have not tested this yet.</input>
<output>We may be able to use the existing queue to simplify delivery if we can fix the duplicate-send issue. We haven't tested this yet.</output>
</example>
</examples>

## Final check

Compare the message with the source silently. Check that every distinct point remains, no point has been added, and certainty, directness, questions, options and commitments are unchanged. Then compare the voice with the closest reference. Fix any drift and return only the message.
