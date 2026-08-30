# Repository issue template resolution

Shared procedure for every command that **creates an issue**
(`report-issue`, the `feature-discovery` skill, and any other path that
opens one). It answers a single question: does the target repository
publish an issue template, and if so, what shape must the body be?

A repository can define issue templates that GitHub pre-fills into the
body when someone opens an issue in the web UI. **Creating an issue
through the API or `gh issue create --body-file` applies no template**:
the body is used exactly as supplied. So a project that has gone to the
trouble of defining a template gets ignored by every issue this plugin
files, unless the plugin fetches the template and fills it in itself.
That is what this procedure does.

Like the rest of the issue-creation path, it is **best-effort**. A
project with no template keeps the built-in standard in
`skills/writing-github-issues/SKILL.md` with no error and no warning.
Most repositories have no template, so that is the common case, not a
failure.

Inputs:

- `{org}` / `{repo}` from `ClaudeProject.md` `## Identity`.
- The issue classification the calling command already made (bug,
  security, architecture, tech debt, story).

> Caveat (Windows / auto-run blocks): the queries below contain code
> fences and must be run by hand, not inside a `!`-prefixed auto-run
> block, which truncates at the first fence.

## Session cache

Resolution is one GraphQL round-trip. In multi-issue sessions (audit
mode, a `feature-discovery` breakdown) it would otherwise repeat per
issue rather than once per session.

Cache the result in `.claude/issue-fields-cache.json` under the key
`issue_templates`, merging into whatever that file already holds. This is
the same file `templates/issue-fields-resolution.md` uses, so `execute`'s
Exit cleanup already deletes it and no new scratch file is introduced.

Cache the **empty** result too. "This repository has no template" is an
answer worth keeping for the rest of the session, and caching it stops a
breakdown of twelve stories making twelve identical queries.

If the cache cannot be written (no Python available), carry on with the
resolved value and note once "template cache skipped". The cache is an
optimisation; never fail an issue over it.

## Step 1 — Resolve markdown templates

One query. It returns the templates GitHub itself would offer in the
chooser:

```
gh api graphql -f query='query($o:String!,$r:String!){repository(owner:$o,name:$r){issueTemplates{name about title filename body assignees(first:10){nodes{login}} labels(first:20){nodes{name}}}}}' -f o={org} -f r={repo}
```

Three properties of this query matter:

- It resolves **organisation defaults**. Where an org publishes templates
  in its `.github` repository, every repo in that org inherits them, and
  this query returns the inherited template for a repo that has none of
  its own. You do not need to look in the `.github` repo yourself, and
  you do not need to guess directory paths.
- `body` comes back with the **YAML frontmatter already stripped**, so it
  starts at the template's first real line. If you ever read a template
  file directly instead, strip the leading `---` block yourself. A body
  that opens with `---` and `name:` means the frontmatter leaked into the
  issue.
- `name`, `about` and `title` are the chooser metadata, and `labels` /
  `assignees` are the frontmatter values.

## Step 2 — Fall back to YAML issue forms

`issueTemplates` returns **markdown templates only**. A repository whose
templates are all YAML issue forms comes back as an empty list, so an
empty Step 1 is not proof there is no template.

When Step 1 returns nothing, list the template directory:

```
gh api repos/{org}/{repo}/contents/.github/ISSUE_TEMPLATE --jq '[.[] | select(.name | test("\\.ya?ml$")) | select(.name != "config.yml") | .name]'
```

A `404` means the directory does not exist, which is the normal "no
templates" answer rather than an error. On a 404, run the same call
against `{org}/.github` (path `.github/ISSUE_TEMPLATE`) to catch an
org-level form, then stop.

`config.yml` is the chooser configuration, never a template. Skip it.

Read the chosen form with the contents API and decode it.

## Step 3 — Choose which template

- **No templates** — go to Step 7.
- **One template** — use it.
- **Several** — match the classification the command already made against
  each template's `name` and `about`, and pick the one that fits (a bug
  report for a bug, a story or feature template for a story). Where
  nothing clearly fits, prefer a general-purpose template over a specific
  one that would be wrong, and fall back to Step 7 if every template is
  for something else. Do not force a security finding into a template
  written for feature requests.

## Step 4 — Fill a markdown template

The template's structure wins. The standard in
`skills/writing-github-issues/SKILL.md` still governs everything else:
what goes in each section, how much to write, and what gets cut.

- **Keep its headings, wording and order exactly.** Do not rename a
  section to the standard's name, do not reorder, and do not add a
  section the template does not have unless you genuinely need it.
- **Delete the guidance comments.** `<!-- ... -->` blocks are
  instructions to whoever fills the template in. Once a section is
  written they are noise, so remove them.
- **Uncomment only what you use.** A template that parks optional
  sections inside one commented block expects you to lift out the ones
  you need. Uncomment those, fill them, and delete the rest of the block.
- **Replace placeholders.** Empty bullets (`*`) and empty checkboxes
  (`* [ ]`) are slots, not content. Fill them or remove the line.
- **Drop a section you cannot fill honestly** rather than writing "N/A"
  or restating another section to look complete. Keep an empty section
  only where the project clearly treats it as required.

## Step 5 — Fill a YAML issue form

A submitted form renders each answered field into the body as a level-3
heading holding the field's `label`, a blank line, then the value:

```markdown
### Steps to reproduce

1. Run the build
2. Open the page
```

Reproduce that shape:

- One `### {label}` block per `input`, `textarea` or `dropdown` field you
  can answer, in the order the form declares them.
- Skip `markdown` elements. They are static guidance shown in the form
  and never appear in a submitted body.
- Skip a field you cannot answer honestly rather than inventing a value.
  A required field you cannot answer means the form is a poor fit; prefer
  Step 7 over filling it with guesses.
- `checkboxes` render as a task list under the same heading.

## Step 6 — Template metadata

A template can carry frontmatter (markdown) or top-level keys (forms).
Handle each as follows:

- **`labels`** — add them to the labels the calling command already
  resolved. Never replace that set: the workflow's own type, priority,
  lifecycle and provenance labels still apply. Drop any template label
  that does not exist on the repository rather than creating it.
- **`assignees`** — **ignore, always.** Creating an issue is never an act
  of claiming it. New issues must enter the unassigned pool so `execute`
  can select them, and assignment happens only at claim time. A template
  that names assignees does not override that.
- **`title`** — treat as a suggestion. Where `ClaudeProject.md` defines
  an issue prefix convention (`[BUG]`, `[SECURITY]`, `[ARCH]`,
  `[DEBT]`), the project's prefix wins. Use the template's title only as
  a starting point for the words after the prefix, and rewrite it to the
  standard's title rules.
- **`type`** — the org's native issue type. The calling command already
  resolves this through `templates/issue-fields-resolution.md`; let that
  stand rather than overriding it from the template.

## Step 7 — No template

Write the body to the built-in standard in
`skills/writing-github-issues/SKILL.md`: `## Summary` plus only the
sections that carry information.

This is the expected outcome for most repositories. Do not warn about it,
and do not offer to create a template.

## Failure contract

Any failure in Steps 1 or 2 (network, auth, rate limit, an unreadable
template) falls back to Step 7. Note it once in what you report back, in
one line, then carry on and create the issue. A template lookup must
never block an issue from being filed.
