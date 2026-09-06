# Body-file write + validation

Canonical procedure for **every** multi-line body this plugin writes — an issue body, a pull request description, a comment — so the write mechanics, the line formatting and the corruption test never drift between callers. Run it wherever a caller says "write the body following `templates/body-file-write.md`".

## What goes in the file

The text itself is written to `skills/_shared/body-standard.md`, which is the one standard behind every body: an issue, a pull request description or a comment. Its two entry points add only what differs — `skills/writing-github-issues/SKILL.md` for an issue, `skills/pr-body/SKILL.md` for a pull request.

The rule that matters most here, because it is the one the file mechanics make easy to get wrong: **never hard-wrap**. Each paragraph is one single line, however long it runs. Never break prose at 72, 80 or any other column. The only line breaks a body has are the ones markdown needs.

## The rule: a body always goes in a file

A body is prose — fenced code, backticks, `$`, quotes, blank lines — and a shell or a JSON encoder eats every one of those. So **never build a body as a shell argument or inside a JSON string**. Not `--body "..."`, and never `--body -`, which does not read stdin: it sets the body to the literal `-`. That is where the corrupt one-character bodies below come from.

**Write the file with the Write tool**, not the shell: it takes the text exactly as you mean it, with no delimiter to collide with and nothing to escape. From the shell, use a *quoted* heredoc (`<<'BODY'`, never `<<BODY` — unquoted expands `$` and backticks before the file is written) with a delimiter that cannot appear in the text.

Then name the file rather than the text:

- **Issues** — `wf issue-apply` with `"body_file"` on the entry. It is the only path that creates or updates an issue body.
- **PRs and comments** — the `gh` command with `--body-file {file}`, plus whatever flags the caller specifies.

Put anything a later step re-reads in `.claude/` and leave it there for a re-run; delete a temp file once the command returns.

## Validate (read back, apply the corruption test)

Immediately read the body back and confirm it was stored correctly:

```
# pick the matching read for what you wrote:
gh issue view {number}  --repo {org}/{repo} --json body --jq '.body'
gh pr view   {pr_number} --repo {org}/{repo} --json body --jq '.body'
```

Treat the body as **corrupt** if **any** of these is true — not just the single `@` case, since the same escaping/stdin bugs also leave `-`, `.`, `#`, or other lone punctuation:

- It is empty or only whitespace.
- After trimming whitespace it is shorter than ~10 characters.
- After trimming it consists only of punctuation/symbols (e.g. `-`, `@`, `.`, `#`) with no words — a stray shell artifact, not a description.
- **(PR bodies only)** it is missing a required `Closes #N` line for any linked issue — see the caller's "Closes #N" requirement.

## Retry

When the body is corrupt:

1. Re-write the intended body to a temporary file.
2. Re-apply with `--body-file` (the edit form of the same command):
   ```
   gh issue edit {number}  --repo {org}/{repo} --body-file {tempfile}
   gh pr edit   {pr_number} --repo {org}/{repo} --body-file {tempfile}
   ```
3. Delete the temp file.
4. Re-read and apply the **same** corruption test again — not just a "non-empty" check.
5. If still corrupt after the retry, warn the user that the body may need manual editing.

Comments (`gh issue comment` / `gh pr comment`) have no read-back identity to re-edit; for those, the Write step (temp file + `--body-file`) is the whole procedure — the validation/retry applies to issue and PR bodies.
