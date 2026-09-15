# Setup: audit the backlog's issue metadata

Read by `/github-workflow:setup issues` (or `backlog`).

The onboarding's Step 5e records what the org *can* classify an issue with. This checks what the open issues actually carry, because nothing else does: an issue created outside the workflow, or before the org enabled types, sits there with no type and no field values, and no error anywhere says so. It only reads.

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-audit
```

Add `--repo owner/name` to audit a different repository, `--limit N` or `--since 2026-01-01` to work through a large backlog in slices, and `--parents` to also report the parent an issue's body claims but the hierarchy does not have (off by default: a story created through `feature-discovery` already carries its epic, so reading it back out of the body only re-derives what the pipeline knew).

Read the exit code: **0** means every open issue carries its type and its field values; say so and stop. **25** means it found gaps and wrote a spec, by default `.claude/issue-audit-spec.json`. **21** means the org's capabilities could not be read, so there is nothing to audit against; fix that first (run `wf.sh org-capabilities --refresh` and follow its `denied` list) rather than reporting a clean backlog.

On **25**, open the spec. Every value the audit could not infer is the placeholder `TODO`, and `issue-apply` refuses a spec that still contains one, so fill each in. Expect `Priority` and `Effort` to be `TODO` on nearly every issue: nothing on an issue records how urgent or how large it is, so there is nothing to read them off. `Ownership` is proposed only where the title starts `[Manual] ` or `[Browser] `, and is left `TODO` otherwise rather than assuming a code agent can take work nobody has said it can take. Then apply it:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-apply .claude/issue-audit-spec.json
```

The audit proposes no dependency edges, because there is nothing to propose them against: a native blocked-by edge is the only record a dependency has, so it cannot disagree with anything. The one thing it ever reads out of a body is the parent an issue claims, and only when you pass `--parents`. To add or remove an edge, put a `blocked_by` list on the spec entry yourself. It is the complete set, so the edges it names are added and any the issue carries that it omits are removed.

Report the counts by gap kind and name what you changed.
