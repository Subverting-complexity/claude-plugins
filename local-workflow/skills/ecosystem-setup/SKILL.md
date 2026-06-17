---
name: ecosystem-setup
description: "Detect, install, and configure Claude Code companion tools (Graphify, RTK, Headroom, ccusage, ecc-agentshield, Fallow) and write the `.claude/ecosystem.md` cheat-sheet the execute and code-review skills read so the tools get used automatically. Trigger on set up/configure ecosystem or any of those tools, or 'regenerate ecosystem.md'. Not for general project onboarding."
---
<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->

# Ecosystem Setup

Set up commonly used Claude Code companion tools and record what was
enabled in `.claude/ecosystem.md`. That cheat-sheet is what the
`/local-workflow:execute` and `/local-workflow:code-review` skills read
to decide which tools to run automatically — without it, those skills
have no idea the tools are installed.

**Plain-English output.** Anything you show the user should be plain and
high-level for a reader who is not involved in this codebase: explain
what a thing is rather than only naming it, keep it concise, and avoid
the patterns in `_shared/banned-patterns.md`. Full standard:
`_shared/wording-standard.md`.

This whole skill is **optional and additive** — skip any tool the user
declines or that is not relevant. Ask once at the start, with a one-line
sense of what is on offer: "Want to set up any Claude Code companion
tools? They are optional and skippable — a codebase knowledge graph
(Graphify) for graph-grounded answers, terminal/context token optimizers
(RTK, Headroom), cost history (ccusage), a config security scanner
(ecc-agentshield), and TS/JS code intelligence (Fallow)."

Track which tools the user enables. At the end, if at least one tool is
enabled, write `.claude/ecosystem.md` containing only those tools'
entries (see **Generate `.claude/ecosystem.md`** below) and **delete any
`.claude/ecosystem-declined` marker** left by a previous decline — the
project is now opted in.

**If the user declines everything**, write **no** tool cheat-sheet, but do
drop a tiny opt-out marker so nothing nags them again:

```
.claude/ecosystem-declined
```

with this content:

```markdown
# Ecosystem tools declined

This project opted out of Claude Code companion tools. Workflow skills
skip the ecosystem step silently and never prompt for it. To enable tools
later, run `/local-workflow:ecosystem-setup` (or
`/local-workflow:setup ecosystem`) — that deletes this marker and writes
`.claude/ecosystem.md`.
```

This marker is the deliberate-opt-out signal: it carries no tool content
and adds nothing to a workflow context window (skills only check whether
it exists), but it tells the onboarding nudge in `preflight` to stay
quiet. Mention the user can `.gitignore` it if the opt-out is personal
rather than a team decision. (A project with **neither** `ecosystem.md`
**nor** this marker is simply one that never ran setup — that is the only
state the nudge speaks up in.)

If `.claude/ecosystem.md` already exists, this skill **regenerates** it:
re-run detection, let the user add or drop tools, and rewrite the file
from the enabled set. If the user drops every tool during a regenerate,
remove `.claude/ecosystem.md` and write the `ecosystem-declined` marker
instead.

---

## Graphify — codebase knowledge graph

Graphify builds a queryable graph of the codebase so agents get
graph-grounded answers instead of file-searching blind.

**Detect:** `graphify --version`

If not installed, offer install commands and skip remaining config if
the user declines:
```
uv tool install graphifyy   # preferred (isolated env)
# or: pip install graphifyy
```

If installed (or just installed), run these checks in order:

1. **First build** — if `graphify-out/manifest.json` does not exist,
   run `graphify .` from the repo root. Large repos (>500 files) will
   prompt for confirmation; remind the user that docs/images cost tokens
   per file (~200–500 each) while code files are free. After the build:
   ```
   git mv graphify-out/GRAPH_REPORT.md docs/GRAPH_REPORT.md
   git add graphify-out/cache/ graphify-out/manifest.json graphify-out/.graphify_labels.json docs/GRAPH_REPORT.md
   ```
   Tell the user to include these in their next commit. (The cache is the
   token receipt — once committed, any fresh clone rebuilds the graph for
   free via `graphify . --update`.)

2. **`.gitignore`** — add entries if not already present:
   ```
   # graphify — generated artifacts (rebuild via `graphify . --update`, ~10s, 0 tokens)
   graphify-out/graph.json
   graphify-out/graph.html
   graphify-out/cost.json
   graphify-out/.graphify_python
   graphify-out/.graphify_root
   ```

3. **Stop hook** — add to `.claude/settings.json` if not already
   present. Merge under `hooks.Stop[0].hooks` rather than replacing:
   ```json
   { "type": "command", "command": "graphify . --update --no-viz" }
   ```
   This keeps the graph fresh automatically at the end of every Claude
   Code session — right after files change, before the next agent starts.

Ecosystem entry (written to `.claude/ecosystem.md`):
```
## Graphify — codebase knowledge graph
**What it is:** Builds a searchable map of how the codebase connects —
which files, functions, and modules depend on which — so agents answer
"how does X relate to Y" from the graph instead of guessing from a few
open files.
**Use it:** `graphify . --update` after any pull or fresh worktree
(rebuilds from committed cache, ~10s, 0 tokens), then
`graphify query "..."`, `graphify path A B`, `graphify explain X`. Never
load `graph.json` into context directly — it is megabytes of mostly
irrelevant detail.
**The workflow uses it:** in the execute **Plan** phase and the
code-review **evaluation** step — prefer a `graphify query` over blind
file search for structure questions. Kept fresh automatically by the
`Stop` hook in `.claude/settings.json`.
```

---

## RTK — token optimizer

RTK filters boilerplate from Bash output (passing tests, repeated
headers) while keeping errors, diffs, and stack traces. Runs as a
global PreToolUse hook — transparent to normal usage, no per-project
configuration needed.

**Detect:** `rtk --version`, then `rtk gain` (the real test — it must
print savings stats). A bare `rtk --version` can succeed against the
wrong binary: there is a separate, unrelated `rtk` ("Rust Type Kit") on
crates.io. If `rtk gain` errors with "command not found", the wrong
package is installed.

If not installed (or the wrong one is), show the collision-safe install
(`rtk-ai/rtk`):
```
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/master/install.sh | sh
# or, with Rust: cargo install --git https://github.com/rtk-ai/rtk
```
**Do not suggest plain `cargo install rtk`** — that pulls the wrong
package from crates.io. Cannot auto-install; note it and skip config if
the user declines.

If installed correctly, the PreToolUse hook is set up by RTK's own
initializer — do not hand-write it. Check `rtk init --show`; if no hook
is present, offer to run:
```
rtk init -g            # global hook, interactive (patches ~/.claude/settings.json)
# or: rtk init -g --hook-only   # hook only, zero RTK tokens in context
```
Only run it with the user's confirmation, since it edits their global
settings. `rtk init` (no `-g`) installs a project-local hook instead.

Ecosystem entry:
```
## RTK — terminal output token optimizer
**What it is:** Sits between Claude and the terminal and trims the noise
from command output — passing-test spam, repeated headers, verbose
boilerplate — while keeping everything that matters (errors, diffs, stack
traces). Claimed 60–90% fewer tokens on typical dev commands.
**Use it:** nothing to invoke — once `rtk init -g` has installed the
PreToolUse hook, it runs automatically on every Bash command. `rtk gain`
shows savings analytics (and is the test that the correct binary is
installed — there is a same-named "Rust Type Kit" on crates.io);
`rtk gain --history` shows per-command history.
**The workflow uses it:** ambient — every command the workflow runs is
already filtered. No phase calls it directly.
```

---

## Headroom — context compression layer

Headroom compresses what the agent feeds the model — tool outputs, logs,
file contents, retrieved chunks, and conversation history — before the
model reads it, claiming 60–95% fewer tokens with answer quality intact.
It runs locally and is reversible: the originals stay on your machine and
the model pulls full context back when it needs it. It overlaps with RTK
(which only trims terminal output) but covers far more, so the two are
complementary — run one or both.

**Detect:** `headroom --version`, then `headroom perf` to confirm it runs
and show any savings so far.

If not installed, offer install commands and skip the rest if the user
declines (requires Python 3.10+):
```
pip install "headroom-ai[all]"   # Python
# or: npm install headroom-ai    # Node / TypeScript
```

Two ways to wire it into Claude Code — offer whichever the user prefers:

1. **Transparent wrapper** — `headroom wrap claude` launches Claude Code
   with compression applied to its context automatically. Add `--memory`
   and `--code-graph` to carry more project context per token. Nothing to
   configure; the user just launches through the wrapper.

2. **MCP server** — `headroom mcp install` registers an MCP server so
   agents can compress and recover context through tool calls
   (`headroom_compress`, `headroom_retrieve`, `headroom_stats`). Only run
   it with the user's confirmation, since it edits MCP config.

`headroom learn` mines past failed sessions and writes corrections into
`CLAUDE.md` / `AGENTS.md`. Mention it, but do not run it automatically —
it edits project instruction files.

Ecosystem entry:
```
## Headroom — context compression layer
**What it is:** Compresses what the agent sends the model — tool outputs,
file contents, retrieved chunks, and conversation history — before the
model reads it, claiming 60–95% fewer tokens while keeping answers intact.
Runs locally and is reversible: originals stay on your machine and the
model pulls full text back when it needs it.
**Use it:** `headroom wrap claude` runs Claude Code with compression
applied transparently (add `--memory` / `--code-graph` for more context
per token); `headroom perf` shows the token savings. For agent tool-call
access instead of the wrapper, `headroom mcp install` registers an MCP
server exposing `headroom_compress`, `headroom_retrieve`, and
`headroom_stats`.
**The workflow uses it:** ambient — like RTK, it shrinks context with
nothing to invoke per phase. It overlaps with RTK (terminal output) but
goes broader (files, history, RAG).
```

---

## ccusage — Claude Code cost history

ccusage reads local Claude Code JSONL session files and shows cost
breakdowns by day, month, session, or project. Zero-install (npx), no
configuration required. Complements the built-in `/cost` (which only
shows the current session) with full historical data.

Ask if the user wants it in their cheat-sheet. No detection or
installation needed.

Ecosystem entry:
```
## ccusage — Claude Code cost history
**What it is:** Reads your local Claude Code session logs and reports
what you spent, broken down by day, month, session, or project — the
history the built-in `/cost` (current session only) does not show.
**Use it:** `npx ccusage@latest` (also `daily` / `weekly` / `monthly` /
`session` subcommands, and `--instances` to group by project);
`npx ccusage blocks` shows your current 5-hour billing window and a
prediction of when you will hit the rate limit.
**The workflow uses it:** diagnostic — run it yourself to check spend or
pace a long autonomous run against the ~100k-per-session budget. No phase
calls it automatically.
```

---

## ecc-agentshield — config security scanner

ecc-agentshield runs 102 deterministic rules across CLAUDE.md,
settings.json, MCP configs, hooks, and skills — looking for hardcoded
secrets, prompt injection vectors, overly permissive allowlists, and
risky MCP endpoints. Zero-install (npx), no configuration required.
Results are reproducible (no AI involved).

Offer to run it now to get an initial baseline report:
```
npx ecc-agentshield scan      # or: npm install -g ecc-agentshield
```

No configuration step. It auto-discovers the `~/.claude/` directory and
the project's `.claude/` config and prints a graded A–F report (0–100).
The default `scan` is the deterministic, no-AI path; the package also
offers a deeper Claude-powered adversarial mode, but the workflow only
relies on the reproducible `scan`.

Ecosystem entry:
```
## ecc-agentshield — Claude Code config security scanner
**What it is:** A static scanner that runs 102 fixed rules over your
Claude Code config — CLAUDE.md, settings.json, MCP configs, hooks, and
skills — looking for hardcoded secrets, prompt-injection openings,
overly permissive allowlists, and risky MCP endpoints. No AI, so the
same input always gives the same A–F report.
**Use it:** `npx ecc-agentshield scan` from the repo root.
**The workflow uses it:** the execute **audit** mode and the code-review
**evaluation** step — run it when the change touches Claude Code config
files (CLAUDE.md, `.claude/`, hooks, skills, MCP config), and fold any
finding into the Security section.
```

---

## Fallow — codebase intelligence (TS/JS projects only)

Fallow analyzes TypeScript/JavaScript codebases for unused exports,
duplication, complexity hotspots, and architectural drift. Available
as a CLI, VS Code extension, and MCP server for agent tool-call access
directly from Claude Code.

**Only offer this tool if the project is TypeScript/JavaScript** —
check for `package.json`, `tsconfig.json`, or `.ts`/`.js` files at the
repo root. Skip silently for other stacks.

**Detect:** `npx fallow --version` (npx — no install needed for the CLI).

The CLI runs with zero config: `npx fallow` for a first scan, then
`npx fallow dead-code`, `npx fallow dupes`, `npx fallow health`, or
`npx fallow fix --dry-run`.

If the user wants agents to query Fallow directly during tasks, register
its **MCP server** in `.claude/settings.json` (merge under `mcpServers`,
do not replace existing servers):
```json
{
  "mcpServers": {
    "fallow": { "command": "fallow-mcp" }
  }
}
```
That exposes tools such as `analyze` (dead code), `find_dupes`,
`check_health` (complexity), and `audit` (changed-file dead code +
complexity + duplication) for agent tool calls. See
[fallow.tools](https://fallow.tools/) for the paid runtime-intelligence
tier (`check_runtime_coverage`, `get_hot_paths`, `get_blast_radius`).

Ecosystem entry:
```
## Fallow — codebase intelligence (TS/JS)
**What it is:** Analyzes a TypeScript/JavaScript codebase for unused
exports, duplicated logic, complexity hotspots, and architectural drift —
the "what connects to what, and what is dead" picture. Free static
analysis (MIT); an optional paid tier adds production runtime data.
**Use it:** `npx fallow` (no install), then `npx fallow dead-code`,
`npx fallow dupes`, `npx fallow health`, or `npx fallow fix --dry-run`.
With the `fallow-mcp` server in settings.json, agents can call its tools
(`analyze`, `find_dupes`, `check_health`, `audit`) directly.
**The workflow uses it:** the execute **Plan** phase — to avoid
rebuilding logic that already exists — and the code-review **evaluation**
step (Minimality / dead-code) — to flag unused exports and duplication
the diff introduces.
```

---

## Commit reminder hook (optional)

Offer a small Stop hook that nudges *you, the user* at the end of a
session if work was left uncommitted — a deterministic backstop. A hook
fires reliably because the harness runs it; a guideline in CLAUDE.md
only fires if the agent remembers it.

Ask: "Add a reminder that warns you at session end if you have
uncommitted changes?" If yes, merge this into the project's
`.claude/settings.json` under `hooks.Stop[0].hooks` (append — never
replace an existing graphify or other Stop hook):
```json
{
  "type": "command",
  "command": "git status --porcelain | grep -q . && echo '⚠ Uncommitted changes — commit your work before ending the session (see CLAUDE.md).' || true"
}
```

This prints the reminder only when the working tree is dirty; a clean
tree stays silent. It is a nudge, not a blocker — it never fails the
session or auto-commits. Skip silently if the user declines.

---

## Generate `.claude/ecosystem.md`

If at least one tool was enabled:

1. **Write `.claude/ecosystem.md`** — include only the sections for the
   enabled tools, using the compact entries above. Prefix the file with:
   ```markdown
   <!-- Generated by /local-workflow:ecosystem-setup — do not hand-edit. -->
   <!-- Regenerate: /local-workflow:ecosystem-setup                      -->

   # Ecosystem Tools

   ```
   Then append each enabled tool's section in the order: Graphify, RTK,
   Headroom, ccusage, ecc-agentshield, Fallow. If a tool was offered but skipped
   for a reason worth recording (e.g. Fallow on a non-TS/JS repo), add a
   one-line note under the title explaining the omission.

2. **Point CLAUDE.md at it** — if the project's `CLAUDE.md` has a
   "Supplementary Files" table, add a row if not already present:
   ```
   | `.claude/ecosystem.md` | Installed Claude Code companion tool cheat-sheet — graphify queries, cost tracking, security scanning, and codebase intelligence. |
   ```
   If there is no such table (or no `CLAUDE.md`), tell the user they can
   add this pointer once they have a Supplementary Files section, so any
   future session discovers the cheat-sheet.

3. **Commit question** — ask whether to commit `.claude/ecosystem.md`
   with the project (team-shared, all agents benefit) or add it to
   `.gitignore` (personal-only). If personal-only, append
   `.claude/ecosystem.md` to `.gitignore`.

If no tools were enabled, skip this entirely — no file, no table row,
zero tokens in future contexts.
