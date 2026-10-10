# Build — Audit mode

Read this only when `$ARGUMENTS.mode` is `audit`. **Exit cleanup** is in `SKILL.md`.

When `$ARGUMENTS.mode` is `audit`:

1. Read `CLAUDE.md` for project rules if it exists.
2. Review the codebase for issues: bugs, security vulnerabilities, architecture problems, code quality concerns.

   **Ecosystem tools.** If `.claude/ecosystem.md` exists, the project has opted into the tools it lists — run them as part of the audit and fold their findings into the report:
   - **Graphify** → `graphify . --update` then `graphify query` for architecture/dependency questions across the whole tree.
   - **Fallow** (TS/JS) → run it for unused exports, duplication, and complexity hotspots.
   - **ecc-agentshield** → `npx ecc-agentshield scan` to audit the Claude Code config (CLAUDE.md, `.claude/`, hooks, skills, MCP) for secrets, prompt-injection openings, and over-broad allowlists. If `.claude/ecosystem.md` is absent the project opted out — skip this step silently. If a listed tool is not installed, note it in one line and continue the audit; a missing tool never blocks it.
3. Report findings organized by severity (critical, warning, suggestion).
4. Do not make code changes. Do not create branches or commits.
5. Run the **Exit cleanup** so the tree ends clean. Audit makes no code changes, so the tree should already be clean — but the quality gate or a tool may have left incidental churn; reconcile it (or confirm `git status --porcelain` is empty) before ending.
