# Who consumes the plugin

The blast radius of a breaking release cannot be judged without this list, and a project board is not proof of an install. Re-run the check when cutting a major release.

No repository commits the plugin to its `.claude/settings.json`, and none should (see `CLAUDE.md` → Installing the plugin for a project). CadenceReader and Secret.Broker used to, and removed it on 15 September 2026 in Subverting-complexity/CadenceReader#1676 and Subverting-complexity/Secret.Broker#304.

**Configured for `synergy`**, verified by a committed `ClaudeProject.md`. The plugin is driven there from a per-machine install, so nothing in the repository records the dependency, but a breaking release affects each of them:

`CadenceReader`, `Secret.Broker`, `Invexis`, `Refrain`, `Telltale`, `Mutation`, `GoogleAppsScripts`, `GTM-AI`.

This repo dogfoods `synergy` on its own backlog and is configured the same way.
