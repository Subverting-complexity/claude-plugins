# Building a mock-up

Read this when you write the mock-up file. The structure below is a default. Change it when the product needs something else, but keep the principles and the hard rules in `SKILL.md`.

## One file, no network

- Put all CSS in one `<style>` and all script in one `<script>` at the end of `<body>`. Use plain JavaScript with no build step and no framework. If the product uses a framework, copy its look, not its code.
- Inline icons as SVG, and images as SVG or small `data:` URIs. Never link to the project's own server, a private CDN or an image host.
- A web font may load from a public source, such as Google Fonts, with a system font fallback that has similar metrics.
- The `<title>` is the product name and the screen name, such as `Orders · Bulk edit`. Never a tool name.
- Set `lang` to the product's language, such as `en-GB`.

## Reuse the product

- Copy the product's tokens to CSS variables on `:root`, with the same names where you can, so the build team can map them.
- Copy each component that the screens need from the product: the same markup shape, the same classes where you can, and the same states (`:hover`, `:focus-visible`, `:disabled`, `[aria-invalid="true"]`). Build each one once and reuse it.
- Copy the closest existing page for the layout: the same header height, page padding, toolbar, table row height and button padding. A small difference makes users comment on the wrong thing.
- Copy the product's patterns for feedback: its toast, its inline message, its confirm dialog and its empty state.
- Only build the product shell that the screens need: the navigation that leads to them and the header. Other menu items can show but do nothing, or show the product's own "not available" message.

## Keep it calm

- Show only text that the real product would show. No subtitles, intro text, help notes or explanations of the feature.
- Give each screen 1 primary button. Other actions are secondary buttons, a menu, or row actions, as the product does them.
- Prefer 1 list with filters to several lists. Prefer a toggle or a select to several buttons.
- Put rarely needed detail behind a "Show details" control or a row expansion.
- Let tables, lists and cards fill the width of the content area, as the product does. Size the columns as percentages of the width, and give narrow columns, such as a check box or the row actions, `width: 1%`.
- A dialog has 1 column and the product's default size. It asks only for what the action needs, with sensible defaults already set. It ends with 1 primary button whose label says what will happen, such as `Move 12 tenants`.
- When a summary helps, use the product's own summary cards, with 3-4 figures at most.

## Screens and routing

- Put each screen in its own `<section data-screen="name">`. Show 1 screen at a time.
- Route with the hash, such as `#orders`, `#orders/edit` or `#orders?state=empty`. A `hashchange` listener shows the right screen and state, so a person can send a link to 1 screen in 1 state.
- Each step writes a new hash, so the browser Back button moves back through the flow.
- Make every screen reachable by clicking from the start screen. A screen that only a hash link reaches is a bug.
- Dialogs, drawers and menus open over the current screen. A dialog traps focus, closes on Escape, and returns focus to the control that opened it.

## Data and behaviour

- Keep the invented data in one `const DATA = {...}` near the top of the script. Make it varied: long and short names, a missing value, and enough rows to show paging or scrolling.
- Keep the state in one object, and draw the screen from it. An action changes the state, then draws again.
- Fake what needs a server. A save waits about 600ms, shows the loading state, then shows success.
- Forms check their input as agreed, show the message next to the field, and set `aria-invalid` and `aria-describedby`.
- Changes last until the page reloads. Do not use `localStorage` for product data.

## States that the product cannot reach

Most states are reachable by clicking: an empty list after a filter, an error after a bad input. If a state cannot be reached by clicking, such as a failed save or a user with no permission, add a small, plain button in a corner, closed by default, that lists those states as hash links. Keep it apart from the product, so nobody reads it as a product feature. Leave it out when every state is reachable.

## Sizes

- Build for the sizes that the brief agreed. Use the product's breakpoints.
- At a small size, the layout changes as the product does it: a side bar becomes a menu, a table becomes a list of cards, and so on.

## Accessibility

- Use real elements: `<button>` for actions, `<a>` for navigation, `<label>` for every field, `<table>` for tables.
- Use landmarks: `<header>`, `<nav>` and `<main>`.
- Every control has a visible `:focus-visible` outline and a name that a screen reader can read.
- Announce a change that a user cannot see, such as a saved message, in an `aria-live="polite"` region.
- Text meets WCAG AA contrast (4.5:1). Large text and control edges meet 3:1.
- When `prefers-reduced-motion` is set, stop every animation and transition.
