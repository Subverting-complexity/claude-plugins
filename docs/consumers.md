# Who consumes these plugins

The blast radius of a breaking release cannot be judged without this list,
and a project board is not proof of an install. Verified against committed
`.claude/settings.json` and `ClaudeProject.md` on 4 September 2026 — re-run
the check when cutting a major release.

**Committed plugin declaration** (`enabledPlugins` in
`.claude/settings.json`, so every session in the repo enables it):

| Repo | Plugin |
| ---- | ------ |
| `CadenceReader` | `github-workflow` |
| `Secret.Broker` | `github-workflow` |

**Configured for `github-workflow` but no committed declaration** — these
carry a `ClaudeProject.md`, so the plugin is driven there from a
per-machine install. They are affected by a breaking release just as much,
but nothing in the repo records the dependency:

`Invexis`, `Refrain`, `Telltale`, `Mutation`, `GoogleAppsScripts`,
`GTM-AI`.

This repo dogfoods `github-workflow` on its own backlog and is configured
the same way.
