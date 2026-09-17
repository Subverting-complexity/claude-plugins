# Bulk-execute — resizing, dropping and the 90-minute timeout

Read this only when the group does not fit the session budget, a story has to be dropped, or the 90-minute timeout is reached.

- **Re-size the group at Phase 3.** If the plan does not fit, drop stories before writing any code (`references/set-selection.md`, **Dropping a story**).
- **A pull request only ever closes stories it built.** If the budget runs out with stories unbuilt, drop them and open the PR for what was built.
- **90-minute timeout.** Before each wave and each phase, check the elapsed time. Past 90 minutes: commit and push, drop the unbuilt stories, then run Phase 7 for a real pull request covering the built ones and carry on into Phases 8 to 10. A group not yet started is dropped whole (`wf drop-group`). If nothing is shippable, leave the branch pushed, set every claimed issue to `stage-attention` with a comment listing what remains, file follow-ups, and run **Exit cleanup**.
