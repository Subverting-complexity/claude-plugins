# Execute — Phase 8 self-review fallback

Read this only when Phase 8 step 2 could not spawn any subagent at all: no agent-spawning tool is offered, or nested spawning is unavailable because `execute` is itself running as a subagent.

Do not skip the review. **Try the general-purpose subagent first**: the usual cause is that the `synergy:Reviewer` agent type is unavailable, not that spawning is impossible, and a general-purpose agent in a fresh context is still genuinely independent. Only when that also fails, run `/synergy:pr-review {pr_number} --read-only` inline in this session, and record that this happened — `mkdir -p .claude && touch .claude/self-review.flag` — so the disclosure below survives a compaction the way the other flags do. **The severity rubric** in `review-and-merge.md` governs an inline review exactly as it governs an agent's.

An inline review is a **self-review**: the same context that wrote the code judges it, so it is weaker evidence than this phase is designed to produce, and it pulls that skill's whole hot path into this session. It does **not** stop the merge. What it obliges you to do is say so in both places a person will look — the PR comment and your final report:

> ⚠ This review was **not independent**. No separate agent context could be spawned, so the session that wrote this code also reviewed it. Its findings are worth less than a fresh reviewer's.

Merging on a disclosed self-review is deliberate (why: `docs/rationale/execute-rationale.md`). The gates that do stop the merge — a failing quality gate, an unapproved verdict, red or absent CI — all still apply, and they are the ones carrying real evidence about the code.
