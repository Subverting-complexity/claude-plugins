# Building a mock-up

This file describes how to put a mock-up together in one standalone `.html` file. The structure below is a default. Change it when the product needs something else, but keep the hard rules in `SKILL.md`.

## One file, no network

- Put all CSS in one `<style>` and all script in one `<script>` at the end of `<body>`. Use plain JavaScript with no build step and no framework. If the existing system uses a framework, copy its look, not its code.
- Inline icons as SVG, and images as SVG or small `data:` URIs. Never link to the project's own server, a private CDN or an image host.
- A web font may load from a public source, such as Google Fonts. Give it a system font fallback with similar metrics, so the page still looks right with no network.
- The `<title>` is the product name and the screen name, such as `Orders · Bulk edit`. Never the word "mock-up" alone, and never a tool name.
- Set `lang` to the product's language, such as `en-GB`.

## Look

- Define every colour, font size, space, radius and shadow once, as a CSS variable on `:root`. For an existing system, take the values from its tokens and keep its names where you can, so the build team can map them.
- Build each component once as a CSS class with its states (`:hover`, `:focus-visible`, `:disabled`, `[aria-invalid="true"]`), and reuse it.
- Match the existing system to the pixel where you can: the same header height, the same table row height, the same button padding. A small difference makes the users comment on the wrong thing.

## Screens and routing

- Put each screen in its own `<section data-screen="name">`. Show one screen at a time.
- Route with the hash, such as `#orders`, `#orders/edit` or `#orders?state=empty`. A `hashchange` listener shows the right screen and state. A person can then send a link to one screen in one state.
- The browser Back button moves back through the flow, because each step writes a new hash.
- Dialogs, drawers and menus open over the current screen. A dialog traps focus, closes on Escape, and returns focus to the control that opened it.

## Data and behaviour

- Keep the invented data in one `const DATA = {...}` near the top of the script. Make it varied: long and short names, a missing value, and enough rows to show paging or scrolling.
- Keep the mock-up's state in one object, and draw the screen from it. An action changes the state, then draws again. This keeps every screen consistent after an edit.
- Fake what needs a server. A save waits about 600ms, shows the loading state, then shows success. A step that can fail has a way to show the failure, from the review panel.
- Forms check their input as the agreed rules say, show the message next to the field, and set `aria-invalid` and `aria-describedby`.
- Changes last until the page reloads. Do not use `localStorage` for product data, so each person who opens the file starts from the same place.

## The review panel

The review panel lets a reviewer reach every screen and state without hunting for it. It is part of the file, not the product.

- Put it behind a small, quiet button in a corner. It is closed by default, and the backtick key toggles it.
- It lists each screen and, under each, its states. Each item is a link to its hash.
- It has a `Reset` button that restores `DATA` and the start screen.
- It may list the open points, each with the option the mock-up shows for now, when the person wants users to see them.
- Style it as plainly as possible, and keep it clearly apart from the product, so nobody reads it as a product feature.

## Sizes

- Build for the sizes the grooming brief agreed. Use the existing system's breakpoints where there are any.
- At each size, the layout changes as the real product would: a side bar becomes a menu, a table becomes a list of cards, and so on, as agreed.

## Accessibility

- Use real elements: `<button>` for actions, `<a>` for navigation, `<label>` for every field, `<table>` for tables.
- Use landmarks: `<header>`, `<nav>`, `<main>`, and an `aria-label` when there are 2 of a kind.
- Every control has a visible `:focus-visible` outline, and a name a screen reader can read.
- Announce a change that a user cannot see, such as a saved message, in an `aria-live="polite"` region.
- Text meets WCAG AA contrast (4.5:1), and large text and control edges meet 3:1.
- When `prefers-reduced-motion` is set, stop every animation and transition, and show the final state at once.
