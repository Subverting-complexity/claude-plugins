# Execute and bulk-execute — quality gate failure

Read this only when Phase 5's retries are exhausted and the quality gate is still red.

Stop retrying, commit what you have, set the gate-failed flag (`mkdir -p .claude && touch .claude/gate-failed.flag`; Phase 10 reads it long after this decision, and a compaction in between would otherwise lose it and merge a red PR), and go to Phase 7. Phase 7 opens a real PR, never a draft, that enters review as changes-requested and carries a "Quality gate failed" section, so a person sees it and the label blocks the merge.
