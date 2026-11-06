# Grooming a mock-up

This file gives the grill its subject, its sources and its coverage list for a mock-up. `skills/grill/SKILL.md` decides how the questions are asked. This file decides what must be covered.

## Sources

Settle every question that a source answers, and show the person what you found. Spend their time on what only they know: what users need, and how the product should feel.

For an existing system, read these in the codebase before you ask anything:

- **Design tokens.** CSS variables, a Tailwind config, a theme file, a design system package or a style guide. Copy the exact colours, type scale, spacing, radii and shadows.
- **Components.** The buttons, inputs, tables, cards, dialogs, menus and navigation the screens use. Note how each looks in its hover, focus, disabled and error states.
- **The screens around the change.** The layout, the navigation, the header and the pages a user comes from and goes to. The mock-up must fit between them.
- **Words.** The labels, messages, tone and terms the product uses today. Use the same word for the same thing.
- **Icons and images.** The icon set and the logo. Inline what you need as SVG.
- **Behaviour.** How the product validates input, confirms a delete, shows a loading state and reports an error today.

If the app runs, and the person agrees, look at it in a browser to see what the code does not show. Do not sign in with real credentials. If a source is not available, ask the person for screenshots.

For a new system, read the design, the spec, the issue or the notes in full. Then read the brand guide or house style, if there is one.

## Coverage list

The grill closes only when every topic below is answered, settled from a source, or deferred with a reason.

1. **Purpose.** What problem the screens solve, for whom, and what a user can do afterwards that they cannot do today. What the mock-up must prove to its audience.
2. **Audience of the mock-up.** Who will open the file: end users, stakeholders or the build team. What they must decide or comment on after they see it.
3. **Users and tasks.** Each kind of user, their role, and the 2-5 tasks they come to do. What each user can and cannot see or do.
4. **Screens.** The list of screens, dialogs and panels in scope. What is deliberately out of scope.
5. **Flows.** Each path a user takes, step by step, from where it starts to where it ends. The happy path first, then the other paths: cancel, back, undo, a wrong input, a lost connection.
6. **Layout and navigation.** Where each screen sits in the product, how a user reaches it, and what stays fixed (header, side bar, footer).
7. **Look and feel.** For an existing system, confirm that the mock-up follows the system, and agree any planned change to it. For a new system, agree the palette, type, density, corner style, depth and tone. Name 2-3 words for the feel, such as "calm, dense, precise", and test each design choice against them.
8. **Content.** The real labels, headings, help text and messages. The data each screen shows, its shape, and how long and how varied it gets.
9. **Functionality.** What each control does. Sorting, filtering, search, paging, editing, bulk actions, keyboard shortcuts. What the mock-up only pretends to do, such as saving or sending.
10. **States.** For each screen: empty, loading, partial, full, error, success, read-only and no permission, where they apply. Validation rules and the error message for each.
11. **Feedback and motion.** How the product confirms an action: a toast, an inline message, a change of state. Which transitions it uses, and how fast.
12. **Sizes and devices.** The screen sizes to support, such as desktop at 1440px and phone at 390px. Touch or mouse. Whether dark mode is in scope.
13. **Accessibility.** Keyboard order, focus, screen reader labels, contrast and reduced motion. Any known need of the users.
14. **Open points.** Each question nobody can answer yet, with the option the mock-up shows for now.

## Where to push

In addition to the grill's own list, push on these:

- **The second user.** Screens are often designed for one role. Ask what a user with fewer permissions sees.
- **The empty first day.** Ask what a new user sees before there is any data.
- **The long name and the large list.** Ask what happens with 3 items, 300 items and a name of 80 characters.
- **The change to the old screen.** For an existing system, ask what happens to the users who know the current screen, and what moves or goes away.
- **Feel words that conflict.** "Simple" and "powerful" pull in different directions. Ask which one wins when they conflict.

## The grooming brief

When the grill closes, write the brief in the chat, not in a file. It must be readable in 2 minutes:

- **Purpose and audience.** 1-2 sentences.
- **Screens and flows.** A short list. Each flow as a line of steps joined by `→`.
- **Look.** Follows the existing system, or the agreed palette, type and feel words.
- **States and sizes.** What each screen shows, at which sizes.
- **Pretend behaviour.** What the mock-up fakes, such as saving.
- **Open points.** Each with the option the mock-up shows for now.

Ask the person to confirm the brief before you build.
