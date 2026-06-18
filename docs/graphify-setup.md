# Graphify setup playbook

## What this gives you

A queryable knowledge graph of your codebase that any agent or developer can
use without rebuilding from scratch. Once set up, agents run
`graphify query "..."` to get graph-grounded answers instead of searching
files blindly. The graph stays fresh automatically via a Claude Code hook.

---

## Step 1 — Install graphify

```
uv tool install graphifyy   # preferred (isolated env)
# or: pip install graphifyy
```

Verify: `graphify --version`

---

## Step 2 — First cold build

Run from the repo root. If the corpus is over 500 files, graphify will warn
you and show top subdirectories — pick a subfolder or confirm full repo.

```
graphify .
```

This runs in two parallel tracks:

- **AST extraction** — static analysis of all code files, deterministic, zero tokens
- **Semantic extraction** — LLM extraction of docs, images, YAML fixtures;
  costs tokens per file (~200–500 each)

For a ~1,000 file repo expect: 25–40k input tokens, 8–12k output tokens for
the semantic pass. Code-only repos cost nothing.

If you have a Gemini API key, set it before running to use Gemini instead of
Claude subagents for semantic extraction (cheaper, faster):

```
export GEMINI_API_KEY=your_key
pip install 'graphifyy[gemini]'
graphify .
```

After the build, outputs land in `graphify-out/`:

```
graphify-out/
  graph.json            ← 4–8 MB assembled graph
  graph.html            ← interactive community visualisation
  GRAPH_REPORT.md       ← god nodes, surprising connections, suggested questions
  cache/                ← extraction cache (the spent-tokens record)
    ast/                ← one file per code module, deterministic
    semantic/           ← one file per doc/image, keyed by sha256(content)
    stat-index.json     ← local size/mtime fast-path index (ignored — churns)
  manifest.json         ← local path→hash index for --update (ignored — churns)
  .graphify_labels.json ← community names (edit these to be meaningful)
  cost.json             ← cumulative token cost tracker
  .graphify_python      ← local interpreter path
  .graphify_root        ← local scan root path
```

---

## Step 3 — Commit the right things

The rule: commit what makes future runs free and preserves human effort.
Ignore what is large, derived, or machine-local.

### Add to `.gitignore`

```
# graphify — generated graph artifacts (large, derived, or machine-local)
# Agents rebuild graph.json locally from cache: `graphify . --update` (0 tokens, ~10s)
graphify-out/graph.json
graphify-out/graph.html
graphify-out/cost.json
graphify-out/.graphify_python
graphify-out/.graphify_root
# Path/mtime indexes: embed absolute worktree paths + timestamps, so they
# churn on every run in every worktree. The content-addressed cache stays
# committed; these rebuild locally for free.
graphify-out/manifest.json
graphify-out/cache/stat-index.json
```

### Commit these files

```
git add graphify-out/cache/            # cache/ast + cache/semantic only — stat-index.json is ignored
git add graphify-out/.graphify_labels.json
git mv graphify-out/GRAPH_REPORT.md docs/GRAPH_REPORT.md
git add docs/GRAPH_REPORT.md
```

### Why each one

| File | Why commit |
|------|------------|
| `cache/ast/`, `cache/semantic/` | Content-addressed: `sha256(file)` → extraction result. This is the token receipt. Any agent cloning the repo runs `--update` and hits 100% cache — zero tokens, ~10s. Without this, every fresh clone spends the full token cost again. |
| `.graphify_labels.json` | Your hand-curated community names. Small (5–15 KB), took real effort, used in the report and visualisation on every re-run. Lose it and you're back to "Community 0", "Community 1". |
| `docs/GRAPH_REPORT.md` | Human-readable point-in-time architecture snapshot — god nodes, surprising connections, community map. Diffs cleanly, renders in GitHub, useful alongside ADRs. In `docs/` so it's findable. |

### Why ignore everything else

| File | Why ignore |
|------|------------|
| `graph.json` | 4–8 MB assembled blob. Rebuilds from cache in ~10s with zero tokens. Permanent git history bloat for no diffable value. |
| `graph.html` | Derived from `graph.json`. Same reason. |
| `cost.json` | Personal/per-machine token spend tracker. Irrelevant to other developers. |
| `.graphify_python` | Absolute path to your local Python interpreter. Breaks on every other machine. |
| `.graphify_root` | Absolute path to your local repo root. Same problem. |
| `manifest.json` | Path→hash index keyed by **absolute** worktree paths, with mtimes. Rewritten on every run, so it churns in every worktree and dirties the tree. `--update` rebuilds it locally for free by re-hashing against the committed content cache (CPU only, zero tokens). |
| `cache/stat-index.json` | Same problem as `manifest.json` — a size/mtime fast-path index of absolute paths. Local rebuild state, not a token receipt. |

---

## Step 4 — Add the Stop hook

Add to `.claude/settings.json`. This runs `graphify . --update` silently at
the end of every Claude Code session — right after an agent finishes a story,
when files just changed.

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "graphify . --update --no-viz"
          }
        ]
      }
    ]
  }
}
```

**Why a hook and not CI:**
CI runs on GitHub's remote runners which have no Claude session. If a doc file
changes and misses the semantic cache, CI would need a `GEMINI_API_KEY` secret
or it silently fails. The Stop hook runs locally where Claude is already
authenticated — cache hits are free, genuine doc changes extract naturally, no
credentials to manage.

**Why not a git hook (`post-commit`, `post-merge`):**
Git hooks aren't committed (they live in `.git/hooks/`), so every developer
has to install them manually. The Claude Code Stop hook is in `settings.json`,
which is committed — it travels with the repo and applies to all agents
automatically.

`--no-viz` skips regenerating `graph.html` on every session end. Agents query
via `graphify query`, not the visual output. Generate the HTML manually when
you want to browse the graph: `graphify export html`.

---

## Step 5 — How agents use the graph

After any `git pull` / fresh worktree, first rebuild:

```
graphify . --update
# Reads manifest.json → finds changed files
# Checks cache/ → all hits on a fresh clone (0 tokens, ~10s)
# Writes graph.json locally
```

Then query:

```
# BFS — broad context
graphify query "How does RequestContext flow through the use case layer?"

# Shortest path between two concepts
graphify path "AuthModule" "Database"

# Plain-language explanation of a node
graphify explain "SagaStepExecutor"

# MCP server — exposes query/path/explain as tools for agent tool-call access
graphify . --mcp
```

Do not load `graph.json` directly into an agent's context — at 4–8 MB it
consumes most of a context window and most of it is irrelevant to any given
question. Use `graphify query` to get surgical, token-budgeted answers.

---

## Token cost reference

| Scenario | Tokens |
|----------|--------|
| Cold full build (code only) | 0 — AST is free |
| Cold full build (with docs/images) | ~200–500 per doc/image file |
| Warm `--update` (all cached) | 0 |
| `--update` after code-only changes | 0 — AST re-extraction only |
| `--update` after 2–3 doc changes | ~500–1,500 total |
| `--update` after a doc sprint (10+ files) | ~3,000–8,000 total |

Once the cache is committed, the only ongoing token spend is for genuinely new
or edited non-code files. Code changes — which are the vast majority of commits
— are always free.
