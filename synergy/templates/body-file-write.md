# Body-file write

Canonical procedure for **every** multi-line body this plugin writes — an issue body, a pull request description, a comment — so the write mechanics and the line formatting never drift between callers. Run it wherever a caller says "write the body following `templates/body-file-write.md`".

What goes *in* the file is decided elsewhere — only where the caller has not already pointed you at it, `skills/_shared/body-standard.md`, through `skills/writing-github-issues/SKILL.md` for an issue or `skills/pr-body/SKILL.md` for a pull request. The one rule these mechanics make easy to break: **never hard-wrap**. Each paragraph is one line, however long it runs.

## The rule: a body always goes in a file

A body is prose — fenced code, backticks, `$`, quotes, blank lines — and a shell or a JSON encoder eats every one of those. So **never build a body as a shell argument or inside a JSON string**. Not `--body "..."`, and never `--body -`, which does not read stdin: it sets the body to the literal `-`. That is where the corrupt one-character bodies below come from.

**Write the file with the Write tool**, not the shell: it takes the text exactly as you mean it, with no delimiter to collide with and nothing to escape. From the shell, use a *quoted* heredoc (`<<'BODY'`, never `<<BODY` — unquoted expands `$` and backticks before the file is written) with a delimiter that cannot appear in the text.

Then name the file rather than the text:

- **Issues** — `wf issue-apply` with `"body_file"` on the entry. It is the only path that creates or updates an issue body.
- **A new PR** — `wf pr-create --body-file {file}`. It does the read-back, the corruption test and the retry below itself, and adds any missing `Closes #N` line, so a caller runs none of it by hand.
- **An edited PR body, and comments** — the `gh` command with `--body-file {file}`, plus whatever flags the caller specifies.

Put anything a later step re-reads in `.claude/` and leave it there for a re-run; delete a temp file once the command returns.

Comments (`gh issue comment` / `gh pr comment`) have no read-back identity to re-edit; for those, the Write step above (temp file + `--body-file`) is the whole procedure. Only for an issue or a pull request body, where a read-back identity exists, read `templates/body-validate-retry.md` and follow it.
