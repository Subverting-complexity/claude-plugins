---
name: mockup
description: 'Groom the look, feel and behaviour of screens, then build a clickable standalone HTML mock-up for users. Trigger on mocking up or prototyping screens.'
---
# Mock-up

This skill runs a grooming session on how a system looks, feels and works, then builds a clickable mock-up of the result. The mock-up is one standalone `.html` file. A person can send it to users, and the users see exactly what the product would look like and how it would behave.

The system is one of 2 kinds:

- **An existing system.** The mock-up shows a change to screens that exist today. It must look like the real product, so a user cannot tell where the real product stops and the change starts.
- **A new system.** The mock-up shows screens that a design, a spec or a set of notes describes, but that nobody has built.

A mock-up is not a demo. A demo explains how a system works, with steps and diagrams. A mock-up is the product itself, as the user will meet it. When the person wants an explainer of a system or a proposal, use the `demo` skill instead.

`skills/user-facing-communication/SKILL.md` shapes what you say to the person around the session and the mock-up: lead with the file path and the current state, keep it short, and surface open points and assumptions. It governs your replies, not the text on the page.

## Process

1. **Read the sources.** Read everything that describes the screens, in full, before you ask anything. For an existing system, read the code and take its look from it, as `references/grooming.md` describes under **Sources**. For a new system, read the design, the spec or the notes. If the project has its own instructions (for example its `CLAUDE.md`), read them for where mock-ups are saved and any extra rules.
2. **Run the grooming session.** Run `skills/grill/SKILL.md` as the interview. The subject is the screens to mock up. The coverage list is in `references/grooming.md`, and the grill does not close until every topic on it is answered or deferred with a reason. Settle from the sources each question they answer, and show the person what you found.
3. **Confirm the brief.** Close with the grooming brief that `references/grooming.md` describes: the screens, the flows, the look, the states and the open points. Ask the person to confirm it before you build. A change to the brief costs a minute now and an iteration later.
4. **Build.** Write the page as `references/build.md` describes. Build the screens first, then the flows between them, then the states.
5. **Verify.** Run every check in `references/verification.md`, look at every screenshot, and fix what you find. Repeat until every screen and state is clean at each size.
6. **Hand over.** Give the person the file path, the screens and flows to try, and the open points. Say how a user moves through it in 1-2 lines.
7. **Iterate.** Feedback from users or the person starts a short grooming round on the changes only, then a new version of the file.

## What makes a good mock-up

- **Real, not a sketch.** It has the final look: real type, real spacing, real colours, real icons and believable content. It is never a wireframe, unless the person asks for one.
- **Faithful to the system.** For an existing system, it uses the system's own colours, type, spacing, components, icons and words. A change looks as if the product team built it. For a new system, it follows the brand or the house style. With none, it uses the look agreed in the grooming session.
- **It works.** Every button, link, tab, menu and field that a user can see does something believable. A flow goes from its start to its end. A form checks its input and shows its errors. Nothing is a dead end without a reason.
- **Every state is there.** Each screen has its empty, loading, error, success and permission states where they apply. The person can reach each state, so a user can see it.
- **Believable data.** The data looks like the real data in shape, length and variety: long names, a missing value, a full list and an empty one. All of it is invented.
- **The right sizes.** It works at each screen size that the grooming session agreed, such as desktop and phone.
- **Accessible.** It meets WCAG AA contrast, works with a keyboard and a screen reader, and respects reduced motion. A mock-up that fails here teaches the build team to fail here.

## Hard rules

These rules hold for every mock-up. Keep all of them.

- **A standalone file, never a hosted page.** Write one self-contained `.html` file and give the person its path. Do not publish it as a hosted artifact and do not offer to: a hosted link may be locked to one account, and a plain file can go to anyone. Inline every style, script, icon and image. The file works with no network, except for a web font loaded from a public source, which must have a system font fallback.
- **No AI tools or vendors.** Do not name or suggest an AI tool, model, assistant or vendor anywhere: not in visible text, the title, a comment, a `meta` tag, a class or id name, a data attribute, an alt text or the file name. Do not add a generator tag or a "made with" line. The page must read as the product team's own work.
- **Invented data only.** Use names such as `Fund A`, `Client 1` or `Jordan Lee`, roles, and round or plausible figures. Never use real names, real figures, account numbers, email addresses or identifiers from the source or the codebase. Product names and system names that the users know are allowed when the project allows them.
- **A small sample data tag by default.** Keep a small, quiet `Mock-up · sample data` tag in a corner, styled to suit the product, so nobody takes a screenshot for the real product. Remove it only when the person asks.
- **Do not invent decisions.** Build only what the grooming brief agreed. If a point is still open, show the option the brief chose for now and list it as open when you hand over. Do not fill a gap with your own design and present it as agreed.
- **No review clutter in the product.** The screens look like the product. Notes, open points and controls for reviewers go in the review panel that `references/build.md` describes, which is closed by default.
- **British spelling, no em dashes** in visible text, unless the existing system uses other conventions. Then follow the system.
- **Name the file** `<yyyy-mm-dd> <Screen or feature> Mockup v<x.y>.html`. Each iteration is a new minor version (`v1.1`, `v1.2`). Keep the old versions. Save it where the project's instructions say; with no instruction, ask.
