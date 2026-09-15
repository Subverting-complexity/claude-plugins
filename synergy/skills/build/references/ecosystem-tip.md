# Build — ECOSYSTEM_TIP

Read this only if the project context block in `SKILL.md` printed an `ECOSYSTEM_TIP` line.

**`ECOSYSTEM_TIP` is informational, not a gate.** If the auto-loaded project context block in `SKILL.md` printed an `ECOSYSTEM_TIP` line, this project has not opted into *or* out of the companion tools. Surface it as **one** plain line early in your response — e.g. "Tip: companion tools like Graphify aren't set up. Run `/synergy:ecosystem-setup` to enable them, or skip — it's optional." — then carry on with the task. It never blocks, never repeats within a run, and stops entirely once the user sets up or declines (declining writes `.claude/ecosystem-declined`). If no `ECOSYSTEM_TIP` line was printed, say nothing about ecosystem tools.
