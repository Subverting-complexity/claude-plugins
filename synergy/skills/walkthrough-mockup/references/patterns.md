# Walkthrough patterns

This file describes how `example-dark-system-walkthrough.html` is built. It shows 1 coherent design system, not the rules for every mock-up. Borrow the techniques. Choose your own palette, type, layout and diagram size for each new mock-up.

The sections on navigation, motion and accessibility apply to any look. The token values, the font and the layout numbers belong to this example only.

## Design tokens (this example)

The example defines every colour on `:root` and uses the variables. Do the same in your own palette. The example sets these:

```css
:root{
  --bg:#060a16; --surface:#0d1426; --surface2:#121b33; --line:rgba(255,255,255,.08); --line2:rgba(255,255,255,.14);
  --text:#eaf0fb; --muted:#8a96b2; --faint:#8591ad;
  --teal:#3ddbc8; --blue:#6f8dff; --violet:#a98bff; --gold:#f2c66d; --rose:#f47aa8; --green:#5fd69a;
}
```

- Each accent has one meaning: rose for blocked items and guardrails, gold for approval, trust and open points.
- `--faint` is `#8591ad` at least. A darker grey, such as `#56617d`, fails contrast on the navy background. Check the muted greys of any palette in the same way.
- The body has 2 radial gradients over `--bg`: blue at the top right, teal at the bottom left.
- The diagram canvas has a faint 40px grid, masked to a radial fade, in `.canvas::before`. This is decoration only.
- The example loads Inter from Google Fonts with `preconnect` links, weights 400-800, and falls back to `"Segoe UI", system-ui, sans-serif`. Its scale: 12px uppercase kicker, 26px title, 22px panel heading, 14px lead, 15px and 11.5px diagram labels.

## Layout (this example)

Other layouts are equally valid. Keep the one-screen rule and the small-screen fallback whatever the layout is.

- **One screen.** `body` is `height:100vh; height:100dvh; overflow:hidden` and a flex column. The page never scrolls at desktop size. Only the panel scrolls, and only when its content is too long.
- **Grid.** `.grid` is `minmax(0,1fr) 420px`, one row of `minmax(0,1fr)`. The diagram is on the left and the panel on the right. `.wrap` has `max-width:1680px`.
- **Diagram.** One SVG with `viewBox="0 0 1200 680"`, `width:100%; height:100%`, so it scales to the space. A fixed viewBox with a percentage size is the useful technique; the numbers suit this layout only. The example lays it out in columns with uppercase headers at `y=44`: sources at `x=40`, then stages, the hub near `x=790`, outcomes at `x=1000`, guardrails along `y=616-668`.
- **Panel.** Kicker, `h2`, lead, `.stats` (3 tiles), then `.inset` with the step's example. A step with no stats keeps a 14px spacer.
- **Compact rules.** `@media (max-height:860px)` shrinks the panel heading, lead, stats (number and label in one line), rows, tiles and chart. `@media (max-height:760px)` shrinks them again and tightens the header and step bar. `@media (max-width:1500px)` hides the step names except the current one.
- **Fallback.** `@media (max-width:1100px), (max-height:600px)` returns to normal scrolling: one column, the panel below the diagram, the SVG at `min-width:760px` inside a horizontal scroll, and `padding-bottom:56px` for the banner.
- **Banner space.** With the banner, `.wrap` has `40px` bottom padding (`36px` in the 760px rule). If the person asks to remove the banner, delete the element and its CSS, and set the padding back to `18px`.

## Navigation

- **Steps.** `STEPS` is an array. Each step has `tab`, `g` (the diagram groups in focus, or `null` for all), `kicker`, `h`, `lead`, `stats` (or `null`), `body()` returning HTML, and an optional `mount(panel)` that wires the example.
- **Step bar.** `go(i)` sets the current step, marks the step button `on` and `seen`, sets `aria-current="step"`, disables Back on step 0, and sets the main button to `Next: <next tab> →`, or `Start again ↺` on the last step.
- **Keys.** Left and right arrows move between steps, except when focus is on a button or in the architecture view.
- **Deep links.** `#3` opens step 3 and `#arch` opens the architecture view. `go()` writes the hash with `history.replaceState`, and a `hashchange` listener reads it, so a person can send a link to one step.
- **Diagram groups.** Wrap each part of the diagram in `<g data-g="name">`. A path or particle that joins 2 parts lists both (`data-g="store gate"`). `go()` adds `.dim` (opacity 0.12) to every group that shares no name with `STEPS[cur].g`.
- **Diagram buttons.** Add `class="hit" data-go="n"` to a part that opens step `n`. The script makes it a button (see Accessibility). Keep the `data-go` numbers in step with the order of `STEPS`.
- **Glow.** `flash(selector)` replays a 1.4s gold drop shadow on the matching nodes. Call it when an example in the panel refers to a part of the diagram.

## View switch

- Put the switch in the header as `<div class="viewsw" role="tablist" aria-label="View">` with 2 `role="tab"` buttons that carry `aria-selected`.
- `setView(v)` shows one SVG wrapper and hides the other, sets `body.arch`, changes the hint text, and hides the step bar's steps and buttons in the architecture view, where `.archhint` shows instead.
- Use the same switch to compare 2 components or 2 options. Keep each view's hash (`#arch`, or a name of your own) so it can be linked.

## Architecture view

- `NODES` is an array of `{id, x, y, w, h, c, t, s, what, own, ctl}`: position and size in the `1200x680` viewBox, a colour key from `COL`, a title, subtitle lines, a one-sentence description, an owner (a role, never a person), and a list of controls. `dash:true` marks an outside service. `pills` shows coloured pills instead of the subtitle lines.
- `LINKS` is an array of `[from, to]`. `anchor()` picks the facing edges and `buildArch()` draws a smooth curve, with a moving dot on each solid link.
- Draw dashed frames behind the nodes for each platform or owner, with an uppercase column header. Put cross-cutting concerns (identity, monitoring, erasure) in a row at the bottom.
- Hover adds `.focus` to the SVG: links into and out of the node turn gold, the linked nodes stay bright, and the rest fade.
- Select shows the node in the panel: kicker `Architecture · component`, the title, the description, then a definition list of `Owner`, `Receives`, `Sends to`, and a `Controls` list. Selecting the empty canvas returns to the intro panel.
- Write each open point in `ctl` as `Open: ...`.

## Motion

- Particles: `addPath(d, groups, colour, speed, count)` registers a path. `tick()` places each dot with `getPointAtLength` and fades it in and out with `Math.sin`.
- Ambient motion: the hub core pulses over 3s and the trust ring turns over 60s. Keep both slow.
- Bars grow over 0.9s with an ease-out curve. Give each chart a Replay button.
- Respect `prefers-reduced-motion`: read it once into `RM`. If it is set, remove the particles, skip the frame loops, set bars to their final width, and make a timed sync finish at once. The CSS rule `*{animation:none!important;transition:none!important}` stops the rest.

## Accessibility

Screen reader users of these pages often read by hovering. Every rule below serves that.

- **Landmarks.** Wrap the page in `<main>`. The step bar is a `<nav aria-label="Tour steps">`. The panel is `aria-live="polite"`, so a step change is read out.
- **Diagrams are groups.** Give each diagram SVG `role="group"` and an `aria-label` that says what it shows. Never use `role="img"` on a diagram that has text in it: `role="img"` hides the text inside from a screen reader.
- **Interactive parts are buttons.** Each `data-go` part gets `role="button"`, `tabindex="0"`, an `aria-label` built from its visible text plus `Opens step n: <tab>.`, and a key handler for Enter and Space. Each source pill and each architecture node gets the same treatment, with its own label.
- **Decoration is hidden.** Put `aria-hidden="true"` on paths, particles, icons, the spinning ring, column headers and frames.
- **Charts are images.** A chart that carries meaning gets `role="img"` and an `aria-label` that states all of its content in words.
- **Step buttons.** Label each one `Step n of N: <tab>` (the Overview button is `Overview`). The number is `aria-hidden`. The current one has `aria-current="step"`.
- **Toggles.** A matrix cell or other toggle is a `<button>` with an `aria-label` and `aria-pressed`. Keep focus on it after you redraw it.
- **No important text in CSS `content`.** Use `::before` and `::after` for lines and dots only.
- **Focus.** Every interactive element has a clear `:focus-visible` outline in an accent colour, such as `2px solid var(--teal)` in the example.
- **Size and contrast.** SVG text is 10px or more in viewBox units at the smallest supported window. Muted text meets the contrast rules in `SKILL.md`, never lower.
