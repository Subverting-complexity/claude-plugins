# Verifying a mock-up

Read this when the mock-up is built. Run every check before you hand the mock-up over. A page that opens is not proof that it works: look at each screenshot.

Put helper scripts and screenshots in a scratch folder, never next to the mock-up.

## 1. Script syntax and duplicate ids

Extract the inline script, check it with Node, and look for repeated `id` values:

```python
import re, sys, collections, pathlib
s = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
pathlib.Path(sys.argv[2]).write_text('\n'.join(re.findall(r'<script>(.*?)</script>', s, re.S)), encoding='utf-8')
ids = collections.Counter(re.findall(r'\sid="([^"$]+)"', s))
print('duplicate ids:', [k for k, v in ids.items() if v > 1] or 'none')
```

```bash
python check.py "<mock-up>.html" page.js
node --check page.js
```

## 2. No network and no outside requests

Search the file for `http://`, `https://` and `//` in `src`, `href` and `url(...)`. The only allowed hit is a public web font. Every other hit is a bug: inline the file.

## 3. Screenshots of every screen and state at each size

Take a screenshot of each screen and each state (each hash the page routes to) at each size the brief agreed, such as 1440x900 and 390x844. Use headless Edge, or Chrome with the same flags. `--user-data-dir` keeps the run away from the person's browser profile.

```bash
EDGE="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
URL="file:///C:/path/to/Orders%20Bulk%20Edit%20Mock-up.html"
for size in 1440,900 390,844; do
  for h in orders "orders?state=empty" "orders?state=error" orders/edit; do
    name=$(echo "$h" | tr '/?=' '---')
    "$EDGE" --headless=new --disable-gpu --hide-scrollbars --force-prefers-reduced-motion \
      --user-data-dir="C:\\temp\\mockup-shots\\profile" --window-size=$size --virtual-time-budget=3000 \
      --screenshot="C:\\temp\\mockup-shots\\shot-${size/,/x}-$name.png" "$URL#$h"
  done
done
```

- Encode spaces in the file URL as `%20`.
- Headless mode keeps about 90px of the window for browser chrome, so the bottom of each PNG may be empty. Judge the page above that band.

Open every PNG and check:

- For an existing system, put the screenshot next to a screenshot of the closest existing page. The colours, type, spacing, icons and components match. A user could not tell the 2 apart outside the change.
- For a new system, the look matches the agreed palette, type and feel words.
- No text overlaps, is cut off, or runs out of its box. Long names wrap or truncate as agreed.
- Each state looks finished, including empty, error and no permission.
- The layout at the small size changes as agreed and has no horizontal scroll.
- The page has no banner, tag or label that marks it as a mock-up or sample data.
- Muted text and thin lines are still easy to read.

## 4. Click through every flow

Screenshots show only the first state. Make a scratch copy of the page with a test script before `</body>` that runs each flow in the brief: it clicks each control, fills each form with good and bad input, and checks the result. It writes `PASS`, or `FAIL <step>`, into `document.title`. Add a `window` `error` listener that writes `ERROR <message>` to the title, so a runtime error cannot pass in silence. Then read the title with `--dump-dom`:

```bash
"$EDGE" --headless=new --disable-gpu --user-data-dir="C:\\temp\\mockup-shots\\profile2" \
  --virtual-time-budget=8000 --dump-dom "file:///C:/temp/mockup-shots/test.html" | grep -o '<title>[^<]*</title>'
```

Also check by hand, in the test or with the browser pane:

- Every visible control does something, or is disabled with a reason.
- Back and Escape work.
- Every screen is reachable by clicking from the start screen.
- The keyboard reaches every control in a sensible order, and focus is always visible.

## 5. Banned words, names and dashes

Search the whole file, including comments, attributes and the file name, and fix every hit:

- The name of any AI tool, model, assistant or vendor, and words such as "generated" or "made with".
- Every real person, client, email address, account number, identifier and figure from the source or the codebase. Search for each name you saw while you read the sources.
- Em dashes (`—`) in visible text, unless the existing system uses them.
- American spellings that the users would notice, unless the existing system uses them.

## 6. Calm and in scope

Read each screen and dialog once more, as a user who has not seen the spec:

- No text explains the feature. Remove each subtitle, intro, help note and callout that the real product would not show.
- Each screen and dialog has 1 primary action.
- Each component, icon and pattern comes from the product, or is listed as new design in the hand-over.
- Tables and lists fill the width of the content area.
- No screen outside the scope has changed.
- Remove each control, column or figure that no flow in the brief needs.
