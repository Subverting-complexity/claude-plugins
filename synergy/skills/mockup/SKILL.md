---
name: mockup
description: 'Build a clickable HTML mock-up of new or changed screens in the look of the existing app, for a story, spec or idea. Trigger on mockup, mock-up, mock up, prototype, wireframe or "what would it look like". Not for explainers.'
---
# Mock-up

This skill builds a clickable mock-up of new or changed screens. The mock-up is one standalone `.html` file that a person can send to users. The users see what the product would look like and how it would behave.

A mock-up is the product, as the user will meet it. It is not a demo. When the person wants an explainer of a system or a proposal, use the `demo` skill instead.

`skills/user-facing-communication/SKILL.md` shapes what you say to the person: lead with the file path and the current state, keep it short, and surface open points and assumptions. It governs your replies, not the text on the page.

## The 4 principles

These come first because they decide if the person likes the result. When 2 of them conflict, the earlier one wins.

1. **Reuse before you design.** Build from what the product already has: its layout, navigation, components, icons, colours, type, spacing and words. Find the existing page that is closest to the new one, and copy its structure. Use the product's own summary cards, tables, dialogs, toasts and empty states. Design something new only when the product has nothing that fits, and say so when you hand over.
2. **Change only what is in scope.** Put the new feature where the person agreed. Do not change other screens, and do not add links, menu items or panels to them, unless the brief says so. If the feature seems to belong on another screen too, ask.
3. **Keep it calm.** Show only what the real product would show. Do not add a subtitle, an intro paragraph, help notes, callouts or any text that explains the feature. Give each screen and dialog 1 primary action. Choose sensible defaults, so the user changes as little as possible. Put detail behind a "Show details" control. A dialog has 1 column and the product's default dialog size, unless the content needs more.
4. **Make it work.** Every control that a user can see does something believable. Each flow goes from its start to its end. Each screen is reachable by clicking through the product, not only by a link.

If the product's code, tokens or screenshots are not available, ask the person for screenshots. With none, use a plain, neutral look: 1 accent colour, a system font, white space, and no decoration.

## Process

1. **Read the sources.** Read the story, the spec or the notes in full. For an existing product, read the code as `references/grooming.md` describes under **Sources**, and find the closest existing page. If the project has its own instructions (for example its `CLAUDE.md`), read them for where mock-ups are saved.
2. **Settle the brief.** Settle every point that the sources answer. If the sources leave points open, ask about them in 1 batch, with the option you suggest for each. Only when there is no story or spec and the person wants to explore the idea, run `skills/grill/SKILL.md` with the coverage list in `references/grooming.md`.
3. **Confirm the brief.** Show the short brief that `references/grooming.md` describes, and ask the person to confirm it. If the person said to go ahead without a check, build at once and list the assumptions when you hand over.
4. **Build.** Write the page as `references/build.md` describes: the screens first, then the flows, then the states.
5. **Check.** Run the checks in `references/verification.md` once, look at every screenshot, and fix what you find. Then read the page again against the 4 principles and remove anything that does not need to be there.
6. **Hand over.** Give the file path, the screens and flows to try in 1-2 lines, what you designed new because the product had nothing that fits, and the open points.
7. **Iterate.** When feedback comes, change only what the feedback is about, and save a new version of the file.

## Hard rules

- **A standalone file, never a hosted page.** Write one self-contained `.html` file and give the person its path. Do not publish it as a hosted artifact and do not offer to. Inline every style, script, icon and image. The only allowed network request is a public web font with a system font fallback.
- **No AI tools or vendors.** Do not name or suggest an AI tool, model, assistant or vendor anywhere in the file or its name. Do not add a generator tag or a "made with" line.
- **Invented data only.** Use names such as `Client 1` or `Jordan Lee`, and plausible figures. Never use real names, real figures, email addresses or identifiers from the sources. Product and system names that the users know are allowed.
- **No banner and no reviewer notes.** Do not add a banner or label that says the page is a mock-up or uses sample data, and do not put notes for reviewers on the screens, unless the person asks.
- **Do not invent decisions.** Build only what the brief agreed. Show the suggested option for an open point, and list it as open when you hand over.
- **British spelling, no em dashes** in visible text, unless the product uses other conventions.
- **Name the file** `<Feature> Mock-up.html`, in title case, such as `Script Runner Image Versions Mock-up.html`. Save it where the project's instructions say. With no instruction, ask. When you change a mock-up the person already has, keep the same name unless they ask for versions.
