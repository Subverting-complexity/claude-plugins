# Verifying a walkthrough

Run every check before you hand the page over. A page that opens is not proof that it works: look at each screenshot.

Put helper scripts and screenshots in a scratch folder, never next to the demo.

## 1. Script syntax and duplicate ids

Extract the inline script, check it with Node, and look for repeated `id` values (the regex also finds ids inside template strings):

```python
import re, sys, collections, pathlib
s = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
pathlib.Path(sys.argv[2]).write_text('\n'.join(re.findall(r'<script>(.*?)</script>', s, re.S)), encoding='utf-8')
ids = collections.Counter(re.findall(r'\sid="([^"$]+)"', s))
print('duplicate ids:', [k for k, v in ids.items() if v > 1] or 'none')
```

```bash
python check.py "<demo>.html" page.js
node --check page.js
```

## 2. Screenshots of every step at 2 sizes

Take a screenshot of each step (`#0` to `#N`) and of each extra view (such as `#arch`) at 1870x900 and at 1366x700. Use headless Edge, or Chrome with the same flags. `--force-prefers-reduced-motion` stops the particles so each shot is stable, and `--user-data-dir` keeps the run away from the person's browser profile.

```bash
EDGE="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
URL="file:///C:/path/to/2026-01-15%20Example%20Demo%20v1.0.html"
for size in 1870,900 1366,700; do
  for h in 0 1 2 3 4 5 6 7 8 arch; do
    "$EDGE" --headless=new --disable-gpu --hide-scrollbars --force-prefers-reduced-motion \
      --user-data-dir="C:\\temp\\demo-shots\\profile" --window-size=$size --virtual-time-budget=3000 \
      --screenshot="C:\\temp\\demo-shots\\shot-${size/,/x}-$h.png" "$URL#$h"
  done
done
```

- Encode spaces in the file URL as `%20`.
- Headless mode keeps about 90px of the window for browser chrome, so the page renders shorter than the window and the bottom of each PNG is empty. The test is stricter than a real screen, which is useful. Judge the page above that band.

Open every PNG and check:

- The page fits one screen with no page scroll. The panel content fits, or scrolls only a little at 1366x700.
- No text overlaps another text, a card edge or the banner. Labels fit inside their pills and cards.
- The current step's groups are bright and the rest are dimmed.
- The step bar shows `Next: <step> →`, and the current step's name.
- The banner shows at the bottom, unless the person asked to remove it.
- The architecture view, if any, has no link drawn through a node, and no empty node.
- Muted text and thin lines are still easy to read against their background.
- The page does not look like a copy of the worked example or of the last demo. If it does, change the identity, not only the colours.

Also take 1 screenshot without `--force-prefers-reduced-motion` and compare: motion must add to the page, and the reduced-motion version must still show every final state.

## 3. Interaction test (recommended)

Screenshots show only the first state of each step. To test the clicks, make a scratch copy of the page with a test script before `</body>` that clicks each control, checks the result, and writes it into `document.title`. Then read the title with `--dump-dom`:

```bash
"$EDGE" --headless=new --disable-gpu --user-data-dir="C:\\temp\\demo-shots\\profile2" \
  --virtual-time-budget=8000 --dump-dom "file:///C:/temp/demo-shots/test.html" | grep -o '<title>[^<]*</title>'
```

Top-level `const` and `let` names (`cur`, `go`, `STEPS`) are visible to a second classic script, so the test can call `go(n)` and read state directly. Add a `window` `error` listener that writes `ERROR <message>` to the title, so a runtime error cannot pass in silence.

## 4. Banned words, names and dashes

Search the file before handover, and fix every hit:

- The name of any AI tool, model or vendor.
- Every real person, client, fund, counterparty, account number, security identifier and figure from the source. Search for each name you saw while you read the source.
- Em dashes (`—`) in visible text.
- American spellings that the audience would notice, such as `color` in visible text, `organize` or `center` (CSS keywords are fine).
