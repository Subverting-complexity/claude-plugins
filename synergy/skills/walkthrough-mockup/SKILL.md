---
name: walkthrough-mockup
description: 'Build an interactive one-screen HTML walkthrough of a system or proposal for business readers. Trigger on walkthrough or explainer mock-ups.'
---
# Walkthrough Mock-up

This skill builds one self-contained `.html` page that explains a system or a proposal to a business audience. The reader moves through a short series of steps. Each step shows one idea as a visual they can explore and click.

The point of this skill is a feeling, not a style. A good walkthrough feels premium, calm and alive, and the reader understands the system by playing with it. Each mock-up gets its own look. Two mock-ups made with this skill must not look like copies of each other.

`skills/user-facing-communication/SKILL.md` shapes what you say to the person around the mock-up: lead with the file path and the current state, keep it short, and surface open points and assumptions. It governs your reply, not the text on the page.

## The feeling

Every walkthrough has all of these qualities. None of them depends on a palette or a layout.

- **Premium and calm.** The page is quiet and confident. It uses a restrained palette, generous space and soft depth. Nothing shouts, and nothing looks cheap or crowded.
- **Visual first, very little text.** The picture carries the explanation. Text labels the picture. Put numbers in large figures, not in sentences. If a step feels busy, cut text before you cut visuals.
- **One idea per step.** Each step has a short heading, 1-2 sentences at most, and one visual that shows that idea. A reader who sees only the visual still gets the point.
- **Motion that explains.** Motion shows how things flow, change or connect: data moving along a path, a value growing, a state changing. Motion never decorates. It is slow and smooth, and all of it stops for a reader who asks for reduced motion.
- **Everything is explorable.** What the reader sees, they can select, hover or toggle, and the page answers. Every step has at least one thing to try. The main visual and the step content stay linked: select one, and the other shows it.
- **A clear path.** The reader always knows where they are, what comes next and how to go back. Steps are numbered and can be linked to directly.
- **Depth and polish.** Layers, light, shadow, careful alignment and small transitions make the page feel made with care. Every state looks finished, including empty, selected and focused states.
- **One screen.** At desktop size the whole step fits the window with no page scroll. The page still works on a small screen.
- **Accessible.** A screen reader, a keyboard and a reader who needs reduced motion all get the full content.

Never make it a cartoon: no clip art, no emoji, no bright fills, no playful fonts.

## Choose a visual identity

Before you build, choose a look that suits the subject and the audience. Decide each of these and write the choice down in 1 line:

- **Palette.** Light or dark, warm or cool, and 1 base with 3-6 accents. A finance board may suit a light, paper-like page. An operations system may suit a dark control room. A people process may suit soft warm tones.
- **Typography.** One family, or a pair for headings and body. Pick one that fits the tone, and set a clear scale.
- **Layout.** A diagram beside a panel, a full-width canvas with an overlay, a vertical story with a fixed visual, or something else that fits the content.
- **Diagram style and metaphor.** Columns of stages, a map, layers, a timeline, a cycle, a city, a pipeline. Choose the metaphor that makes this system easy to see.
- **Component mix.** Pick from the menu below, and invent new components when the story needs them.

Do not reuse the last mock-up's identity by default. If the person has a house style or brand, follow it.

## Design rules

These rules hold whatever the look is.

- **Contrast.** Body text meets WCAG AA (4.5:1). Large text and important graphic lines meet 3:1. Check muted text in particular.
- **A type scale.** Use 4-6 sizes with clear steps between them. Do not invent a new size for each element.
- **A limited palette.** Define every colour once as a CSS variable on `:root`. Give each accent one meaning and keep it, such as one colour for blocked items and one for approval.
- **Consistent spacing.** Use one spacing scale and one set of corner radii.
- **Reduced motion.** Read `prefers-reduced-motion` and stop every animation, moving dot and timed change when it is set. Show the final state at once.

## Component menu

These are ideas, not a required set. Each one is good for a kind of point. Pick what suits the story, and leave the rest. The worked example has some of them; the others are not in it, so build them fresh.

| Component | Good for |
| --- | --- |
| System diagram with moving particles | Showing where data comes from and where it goes |
| Focus and dimming | Making the current step stand out from the whole |
| Hub with rings or an orbit | A central service with several roles, or people around one core |
| Gate or decision node | Showing a check that sorts or blocks items |
| Before and after toggle | Today against the proposal, in one place |
| Before and after split | The same view side by side, with a slider between the 2 halves |
| Chips with a detail card | Several inputs or options, where each has a few facts |
| Sorting rows with tags | Showing how example items are routed, and why |
| Horizontal timeline | A sequence of events, phases or releases |
| Timeline with a bar chart and Replay | Who did what, and when, with a result that grows |
| Layered stack | Layers of a platform, or controls that wrap each other |
| Map or flow on a light canvas | Locations, teams or hand-offs, drawn as a calm plan |
| Interactive matrix | Who can see or do what; toggle a cell and see the effect |
| Matrix with a pending sync | A change that takes time to apply |
| Persona chips and a filtered table | The same data as different people see it |
| Question chips and an answer card | What a person could ask, and what they get back |
| Approval stepper | A change that needs people to approve it before it goes live |
| Card carousel | A set of examples, one at a time, with no scroll |
| Stat figures | 2-3 numbers that matter for the step |
| Rule tiles or a guardrail strip | Fixed rules that apply everywhere |
| Architecture view | Each component with its owner, inputs, outputs and controls, with links traced on hover |
| View switch | 2 views of the same system, or 2 options to compare |

## Worked example

`references/example-dark-system-walkthrough.html` is 1 worked example of the feeling: a dark system walkthrough with invented data. Open it in a browser and study how it creates depth, motion, focus and interaction. Borrow techniques from it, such as particles, dimming, deep links or the accessibility wiring. Do not copy it and refill it, and do not take its palette, layout or font as the default.

`references/patterns.md` describes the example's design system and the techniques behind it. Use it as a reference for how one coherent system is put together.

## Process

1. **Read the source first.** Read the proposal, design or notes the page explains, in full. List the stages of the system, who owns each, the numbers that matter and the points that are still open. If the project has its own instructions (for example its `CLAUDE.md`), read them for where mock-ups are saved and any extra rules.
2. **Choose the identity.** Decide the palette, type, layout, metaphor and component mix, as described above. Tell the person the choice in 1-2 lines when you hand over.
3. **Plan the steps.** Plan 5-8 steps, plus an overview if it helps. Each step is one idea with one visual and one thing to try. Check that the plan covers the source.
4. **Build.** Write the page from the plan. Build the visuals first, then add the shortest text that labels them. Mark each open point as open (`Open: ...`).
5. **Verify.** Run every check in `references/verification.md`, look at every screenshot, and fix what you find. Repeat until every step is clean at both sizes.
6. **Hand over.** Give the person the file path, the identity you chose, the steps, and the open points the page shows.

## Hard rules

These rules are about safety and access, not about look. Keep all of them.

- **A plain file, never a hosted page.** Write one self-contained `.html` file and give the person its path. Do not publish it as a hosted artifact and do not offer to: a hosted link may be locked to one account, and a plain file can go to anyone. Load fonts and libraries only from public sources, or inline them.
- **Invented data only.** Use `Fund A`, `Broker 1`, roles such as `Analyst` or `Head of operations`, and round figures. Never use real names, real figures, account numbers or identifiers from the source. System names that the audience knows are allowed when the project allows them.
- **No AI tools or vendors.** Do not name an AI tool, model or vendor anywhere in the page, its title, its comments or its file name.
- **A test banner by default.** Keep a fixed `Mock-up · test data` banner at the bottom of the page, styled to suit the identity, and leave room for it. Remove it only when the person asks.
- **Accessibility patterns.** Follow the accessibility rules in `references/patterns.md`: landmarks, diagrams as `role="group"`, interactive parts as buttons with labels, hidden decoration, charts described in words, focus outlines and keyboard use.
- **Verification.** Run the checks in `references/verification.md` before you hand over.
- **Do not invent mechanisms.** Show only what the source states. If the source leaves a point open, show it as open. Do not fill the gap with a plausible design.
- **British spelling, no em dashes** in visible text. Use a middle dot (`·`) as a separator.
- **Name the file** `<yyyy-mm-dd> <Screen> Mockup v<x.y>.html`. Each iteration is a new minor version (`v1.1`, `v1.2`). Keep the old versions. Save it where the project's instructions say; with no instruction, ask.
