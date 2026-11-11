# Settling a mock-up brief

Read this when you settle the brief for a mock-up: what to read first, what the brief must cover, and how it looks.

## Sources

Settle every point that a source answers. Spend the person's time only on what the sources do not say.

For an existing product, read these in the codebase before you ask anything:

- **The closest existing page.** The page that does the most similar job, such as another admin list with a detail view. Copy its layout, its header, its toolbar, its table and its actions. Note the file, so the build matches it.
- **Design tokens.** CSS variables, a Tailwind config, a theme file or a design system package. Copy the exact colours, type scale, spacing, radii and shadows, and keep their names.
- **Components.** The buttons, inputs, tables, summary cards, dialogs, menus, toasts and empty states that the product already has. Note how each looks in its hover, focus, disabled and error states.
- **Icons.** The icon set the product uses. Inline the exact icons as SVG. Do not mix in a second icon set.
- **The screens around the change.** The navigation and the pages that a user comes from and goes to. The mock-up must fit between them.
- **Words.** The labels, messages and terms the product uses today. Use the same word for the same thing.
- **Behaviour.** How the product confirms a delete, shows a loading state, reports an error and confirms a save.

If the app runs, and the person agrees, look at it in a browser to see what the code does not show. Do not sign in with real credentials. If the code is not available, ask the person for screenshots of the closest pages.

For a new product, read the design, the spec or the notes in full, then the brand guide or house style if there is one.

## What the brief covers

Most of these come from the sources. Ask only about the points that the sources leave open.

1. **Purpose and audience.** What the screens let a user do, and who will open the mock-up.
2. **Users and permissions.** Each kind of user, and what each can and cannot see or do.
3. **Screens in scope.** The screens, dialogs and panels to build, and where each sits in the product. The screens that must not change.
4. **Flows.** Each path from its start to its end: the main path first, then cancel, back and a wrong input.
5. **Content and data.** The labels, and the data each screen shows: its shape, its length and its variety.
6. **States.** Empty, loading, error, success and no permission, where they apply.
7. **Sizes.** The screen sizes to support, such as desktop only, or desktop and phone.
8. **Open points.** Each question that nobody can answer yet, with the option the mock-up shows for now.

The look is not a question for an existing product: the mock-up follows the product. Ask about the look only for a new product, or when the person wants to change the product's look. Accessibility follows `references/build.md` and is not a question either.

## Where to push

Push on these only when they matter for the screens in scope:

- **The second user.** What a user with fewer permissions sees.
- **The empty first day.** What a new user sees before there is any data.
- **The large list.** What happens with 300 items and a name of 80 characters.
- **The old screen.** For an existing product, what changes for users who know the current screen.

## The brief

Write the brief in the chat, not in a file. Keep it short enough to read in 1 minute:

- **Screens.** Each screen, where it sits, and the existing page it copies.
- **Flows.** Each flow as a line of steps joined by `→`.
- **States and sizes.**
- **Pretend behaviour.** What the mock-up fakes, such as saving.
- **New design.** Anything the product has no pattern for.
- **Open points.** Each with the option the mock-up shows for now.
