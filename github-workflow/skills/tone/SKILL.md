---
name: tone
description: "Format and polish correspondence — emails, messages, updates, status reports — in the user's own writing tone. Use whenever the user wants to write, rewrite, or clean up any message, or to strip AI tells (em dashes, generic phrasing) from drafted or pasted text. Handles both light polishing of dictated drafts and full rewrites of non-user input."
---
<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->

# Correspondence Tone Skill

Read `references/examples.md` before editing any text. Those examples are the ground truth for the user's voice.

Read `references/glossary.md` for proper noun corrections, sign-off preferences, and project-specific terminology.

Read `_shared/banned-patterns.md` before writing. All banned patterns apply to correspondence.

The examples file has two sections. The **Golden Reference Examples** at the top are polished writing the user produced themselves, with no dictation artefacts. They are the target output. If an edited message would not fit in that section, the edit has drifted too far from their voice. The **Standard Examples** show the typical shape of their correspondence across work, technical, and client-facing contexts. Study both.

`skills/user-facing-communication/SKILL.md` shapes what you say to the
person **around** the message: lead with the outcome and the current
state, keep it short, and surface anything outstanding or assumed. It
governs your own reply. The polished message keeps the user's voice as
this skill defines it, and nothing here overrides that.

---

## Step 1: Identify the Input Mode

Before editing anything, classify the input. This determines how much work you do. The two modes require very different approaches.

### Hard Override Rules (check these first)

These rules force the mode before you look at anything else:

1. **Em dashes used as stylistic breaks -> Mode B.** If the input contains em dashes used to break into a clause or append a thought, the input is Mode B regardless of how technical or specific the content is. The user does not use em dashes. An em dash is the single most reliable signal that the input was AI-polished.
2. **AI vocabulary from the banned list -> Mode B.** Even one word from the banned vocabulary list (leverage, streamline, robust, holistic, etc.) forces Mode B.
3. **Formulaic openers/closers -> Mode B.** "I hope this finds you well", "Happy to help", "Hope this helps", "Let me know if you have any questions" -> Mode B.
4. **Clean run-on with packed causal chains -> Mode B.** Sentences of the form "X does Y, which triggers Z, so you'd get W" in a single unbroken sentence are AI-written. The user breaks these into sequential short sentences or bullets.

If none of these fire, continue to the signal-based classification below.

### Substance vs Voice

Technical accuracy does not indicate the user's voice. AI produces technically accurate content in its own voice all the time: correct method names, real file paths, accurate backticks around identifiers, domain-correct terminology. These are **substance** signals, not **voice** signals.

The voice signals are separate:
- Short paragraphs, one thought per line
- Personal framing ("I think", "IMO", "my understanding is")
- Risk and trade-off language spelled out ("this is very risky", "the bigger variable is")
- Hedging ("probably", "likely")
- No em dashes, no AI vocabulary

If the input has substance signals but not voice signals, it is Mode B. A technically correct AI rewrite of the user's thinking is still Mode B.

### Mode A: Dictated or already in the user's voice

Signals this is Mode A (must include at least one voice signal, not just substance):
- Dictation artefacts: run-on sentences from speech, duplicated words ("a a", "so it's this is"), proper nouns slightly mangled
- First-person framing already present ("I think", "my understanding is", "I'd estimate")
- Hedging and qualifiers already there ("probably", "likely", "it depends on")
- Short paragraphs with one thought per line
- Concrete specifics (hour estimates, file names, story numbers, tenant names) combined with at least one voice signal
- Structure that resembles a Standard Example
- No em dashes used as stylistic breaks, no AI vocabulary, no formulaic openers

In Mode A, apply **minimal polish only**. Follow the "Core Principle: Minimal Intervention" and "What to Fix" sections below. Do not rewrite. Do not restructure. Do not add voice flourishes that aren't already there. The goal is to make the dictated draft readable, not to transform it.

### Mode B: Not written by the user (AI output, technical explanation, someone else's draft)

Signals this is Mode B:
- Em dashes used as stylistic breaks (**hard override**)
- AI vocabulary (**hard override**)
- Formulaic openers (**hard override**)
- Packed causal chains in single sentences (**hard override**)
- Abstract nominal closers that restate the point at a higher level ("which is the wrong semantic", "which is the correct approach")
- Balanced "not only X but also Y" or "it's not X, it's Y" constructions
- Generic, passive, or third-person framing instead of "I think" / "IMO"
- Tidy summary sentences that restate the previous paragraph
- Closing lines like "Let me know if you have any questions" or "Hope this helps"
- Feels like it could have been written by any professional, not specifically the user
- User explicitly says "rewrite this in my voice" / "make this sound like me" / "this was written by Claude, fix the tone"

In Mode B, do a **full rewrite**. Strip every AI tell. Reshape toward the Golden Reference patterns. Keep the substance, change the voice. The output must read as if the user wrote it themselves: indistinguishable from the Golden Examples or Standard Examples.

### Ambiguous cases

If the draft has a few AI tells but is mostly the user's own words (e.g. they dictated it and then an assistant "cleaned it up" and added em dashes and a sign-off), treat it as **Mode A with Mode B touch-ups**: strip the AI tells but otherwise do not rewrite the content.

If you cannot tell which mode applies after running the checks, default to Mode B. Over-editing to strip AI tells is safer than under-editing and leaving them in.

---

## Core Principle for Mode A: Minimal Intervention

The default is to change as little as possible. Fix typos and grammar errors. Remove accidental duplications ("a a", "so it's this is"). Do not rewrite sentences that are already clear. Do not reorder paragraphs unless the current order actively confuses the meaning. Do not expand, pad, or polish for its own sake.

If a sentence is a bit long or loosely structured and it still makes sense, leave it. That is their voice.

Reordering is allowed only when it genuinely serves the message. When in doubt, do not move it.

One specific case where reordering is appropriate: when a reference or attachment line appears at the end but is needed for the reader to understand what comes before it, move it to just before the relevant content.

---

## Core Principle for Mode B: Full Rewrite Into Their Voice

When the input is not in the user's voice, minimal intervention is the wrong approach. The input voice has to be replaced, not preserved.

The process:

1. **Extract the substance.** Identify what the message is actually saying: the facts, the positions, the decisions, the questions. Ignore the surface wording.
2. **Pick the target shape.** Is this a short chat reply (match a short Golden Example)? A technical pushback (risk framing, alternative, trade-offs laid out)? A formal email? A multi-topic status update? The length and formality of the output is driven by the use case, not by the length of the input.
3. **Rewrite from the substance.** Do not translate sentence-by-sentence from the input. Build the output from the substance using the user's patterns directly.
4. **Apply all banned-pattern filters.** Every item in the banned patterns must be zero in the output. Em dashes, AI vocabulary, formulaic openers, tidy closing lines: all gone.
5. **Pressure-test against the Golden Examples.** If the output does not sound like it could sit in the same file as the Golden Examples, it's not done.

Mode B output should contain:
- First-person framing ("I think", "IMO", "my understanding is", "what would be safer")
- Concrete specifics where the input had abstractions (file names, method names, hour estimates, whatever the domain supplies)
- Backticks around any code references, preserved even if the input didn't have them
- Risk and trade-off language spelled out rather than hedged into smooth prose
- Short paragraphs, one thought per line for chat-style output
- No sign-off for chat; standard sign-off only for email format when matching the user's examples

Mode B output must not contain:
- Em dashes anywhere
- Any word from the AI vocabulary list
- Any formulaic opener or closer from the banned patterns
- Balanced framing that presents pros and cons equally when the user would lean one way
- A tidy closing sentence that summarises what was just said

---

## Mode B Playbook: Matching Their Written Voice

Use this section when the input needs to be rewritten (Mode B). These are the patterns to inject into the output. Derive the specific patterns from the Golden and Standard Examples.

- **Personal framing.** "I think", "IMO", "My understanding is that" where they fit. Do not leave the output in neutral third-person phrasing.
- **Hooks over greetings.** For internal chat, openers like "Hey", a name on its own line, "What about:", or a direct first statement are preferred over formal greetings.
- **Risk and trade-off language stays explicit.** Phrases like "this is very risky", "can quickly get into a place where", "the bigger variable is" should not be softened into hedged corporate language.
- **Preserve inline code formatting.** Backticks around method names, class names, file names, variable names, and property names. Add backticks if the input didn't have them.
- **Bulleted technical proposals are concrete.** Each bullet names a specific location (file, method, component, condition) and the action to take there. Do not abstract them into generic summaries.
- **Short paragraphs, one thought per line.** In written chat replies, reasoning is laid out sequentially with visual breathing room, not packed into dense paragraphs.
- **No sign-off on chat messages.** If the target is a chat message with no greeting, do not add a sign-off. The message ends when the content ends. For email format, use the user's standard sign-off from the examples.
- **Hedging stays.** "Probably", "likely", "IMO", "my understanding" are deliberate. Do not strip them to sound more confident.

If the Mode B output reads like any competent professional wrote it rather than specifically the user, compare it against the Golden Examples and push it closer.

---

## What to Fix (Mode A only)

- Typos and spelling errors
- Duplicate words ("a a", "so it's this is not")
- Grammar errors that change or obscure meaning
- Punctuation that is clearly wrong (missing full stop, unclosed bracket)
- Tangled or run-on sentences where the meaning is genuinely unclear: restructure the minimum needed to make it clear, without adding content
- Clunky or redundant phrasing where a sentence repeats itself or uses an awkward construction; clean it up without changing the meaning
- Dictation near-misses on proper nouns (correct using `references/glossary.md`)

---

## What Not to Do (Mode A only)

These rules apply when polishing the user's own dictated drafts. In Mode B, rewriting is the whole point, so these don't apply.

- Do not rewrite clear sentences to make them sound more polished
- Do not add connectors, transitions, or openers that weren't there
- Do not remove context, background, or reasoning the user included
- Do not choose between options the user was weighing
- Do not change their certainty level in either direction
- Do not add a closing line, summary sentence, or sign-off that wasn't in the draft
- Do not restructure paragraphs to make them more "logical" unless the original order breaks comprehension

---

## No Commentary

Return the edited message only. No "Here's the polished version," no explanation of what changed, no preamble.

---

## For Client-Facing Messages

If something reads as harsh or accusatory, soften the framing without removing the substance. For internal messages, apply no softening.

---

See `references/examples.md` for voice reference material and `references/glossary.md` for project-specific terms.
