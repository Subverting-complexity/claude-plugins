# Execute — Audit mode

Read this file only when `$ARGUMENTS.mode` is `audit`. Audit is a no-code-change pass over the codebase that files issues for findings; it applies to a minority of runs, so it is kept out of the main `SKILL.md`.

When `$ARGUMENTS.mode` is `audit`:

1. Read `ClaudeProject.md` for org, repo, and label map.
2. Audit the default branch — read the codebase structure, key files, and patterns. Check for architecture violations, security issues, test gaps, dead code, and tech debt. Use the evaluation criteria from the code-review skill (non-compliance gates, correctness, security, test coverage) but apply them to the codebase at large, not to a specific PR diff.

   **Ecosystem tools.** If `.claude/ecosystem.md` exists, the project has opted into the tools it lists — run them as part of the audit and turn their findings into issues like any other:
   - **Graphify** → `graphify . --update` then `graphify query` for architecture/dependency questions across the whole tree.
   - **Fallow** (TS/JS) → run it for unused exports, duplication, and complexity hotspots.
   - **ecc-agentshield** → `npx ecc-agentshield scan` to audit the Claude Code config (CLAUDE.md, `.claude/`, hooks, skills, MCP) for secrets, prompt-injection openings, and over-broad allowlists. If `.claude/ecosystem.md` is absent the project opted out — skip this step silently. If a listed tool is not installed, note it in one line and continue the audit; a missing tool never blocks it.
3. For each finding, run `/github-workflow:report-issue` to create a GitHub issue with the appropriate type and priority labels. Cap at 10 issues per audit session to keep scope manageable.
4. Report a summary of all issues created.
5. Do not make code changes. Do not create a branch or PR.
