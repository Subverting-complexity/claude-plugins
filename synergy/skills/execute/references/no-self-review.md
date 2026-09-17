# Execute and bulk-execute — why nothing reviews its own diff

The session that wrote the code shares every assumption it was built on. That decides whose judgement counts, not whether the run continues: you still spawn the reviewer, own what it returns, and hand the PR to nobody (not the user, not a later session, not a standalone `/synergy:pr-review`).

Phase 8's last-resort inline fallback (`references/self-review-fallback.md`) is the one exception, and it is disclosed there.
