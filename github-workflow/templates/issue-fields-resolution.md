# Issue type + field resolution

Shared procedure for every command that **creates or classifies an issue**
(`report-issue`, `execute`'s retroactive issue, and the
`feature-discovery` skill), and for the selector
(`templates/story-selection.md`) when it filters by kind or sorts by
priority. It resolves the org's **native issue types** (Bug, Feature, User
Story, Epic) and **org issue fields** (Priority, Effort, Classification,
Start date, Target date, Parent, Status reason, Origin) **by name at
runtime**, so the plugin never hardcodes an org-specific node id and works
against any target org.

Run the relevant discovery step **once** per command before you set a
native type or a field value. Like board writes, everything here is
**best-effort and capability-gated**: an org that has not configured native
issue types or a given field simply keeps today's label-only behaviour for
that dimension — never error, never block the issue from being created.

Inputs:

- `{org}` / `{repo}` from `ClaudeProject.md` `## Identity`.
- The purpose→value maps in `templates/default-labels.md` →
  *Issue Types & Field Values* (the native-type map, the Classification
  map, the priority/effort maps, and the Origin map), overridable per
  project in `ClaudeProject.md` → `## Issue Types & Fields`.

> Caveat (Windows / auto-run blocks): the queries below contain code
> fences and must be run by hand, not inside a `!`-prefixed auto-run block
> — an auto-run block truncates at the first fence (see issue #33).

## Steps 1 and 2 — Resolve the org's types and fields

Both discovery steps are one command:

    wf org-capabilities [--refresh]

It resolves the org's enabled native issue types and every issue field with
its option ids in a single GraphQL round trip, caches the result to
`.claude/issue-fields-cache.json`, and reads that cache on later runs.
`--refresh` forces a re-query. The `execute` skill's exit cleanup deletes the
cache alongside the other `.claude/` scratch files.

Read the exit code, not the prose:

| Exit | Status | What it means | What to do |
|------|--------|---------------|------------|
| 0 | `ok`, `owner_kind: organization` | Types and fields resolved | Use `type_map` and `field_map` from the JSON |
| 0 | `ok`, `owner_kind: user` | A user-owned repo — issue types are org-only | Classify with `type-*` labels; this is valid, not a fault |
| 21 | `no-capabilities`, with `denied` | The account may not read issue types or fields for this org | Stop. Run `gh auth status`, then `gh auth switch` to an account with access |
| 21 | `no-capabilities` | The org resolves but reports neither types nor fields | Stop. The token is under-scoped — it needs `read:org` |
| 20 | `error` | Not in a repo, no `gh`, auth failure | Fix the environment |

The JSON also carries `resolved_fields` (purpose key → the field name that
exists on this org) and `missing_fields` (the ones that do not), so a caller
knows what it can set without re-deriving the mapping.

It is GraphQL and not REST deliberately: `/orgs/{org}/issue-fields` returns
`null` for every option id, which makes single-select and multi-select fields
impossible to write. The query lives in `wf.ORG_CAPABILITY_QUERY` with that
note attached.

### Reporting a field the org does not define

**Surface each skip, don't swallow it.** When a field the command *intends*
to set (per the table below) is not in the discovered map — never defined,
or renamed away from the configured name — the skip is still correct, but
do it **visibly**: emit one concise line per missing field so an org that
*expects* those fields populated gets a signal instead of silent blanks,
reported together after discovery (Step 5):

```
skipped field 'Effort' (not found in org issue fields)
skipped field 'Origin' (not found in org issue fields)
```

This is informational, never an error — the issue is still created and
still carries its labels.

Field names and their data types are `wf_core.FIELD_NAME_DEFAULTS` and
`wf_core.FIELD_DATA_TYPES`; `wf org-capabilities` reports which of them this
org actually defines. Do not restate them here — the copy that used to live
in this table said `Classification` was single-select for some time after the
org converted it to multi-select, and nothing caught it.

Which command sets which field:

| Purpose key | Set by |
|-------------|--------|
| `field-priority` | report-issue, execute, feature-discovery |
| `field-effort` | every issue-creating command |
| `field-type` | every issue-creating command |
| `field-origin` | every issue-creating command |
| `field-start` | execute (on claim) |
| `field-target` | execute (on PR creation — records actual completion date) |
| `field-parent` | feature-discovery (epic-child link) |
| `field-status-reason` | block-story (blocker description) |

## Step 3 — Get the issue's node id

Field and type mutations key off the issue's GraphQL node id, not its
number. After `gh issue create` returns a URL/number, resolve the id:

```
gh api graphql -f query='query($owner:String!,$repo:String!,$number:Int!){
  repository(owner:$owner,name:$repo){ issue(number:$number){ id } }
}' -F owner='{org}' -F repo='{repo}' -F number={number} \
  --jq '.data.repository.issue.id'
```

## Step 4 — Set the native issue type

Type-capable orgs only (Step 1). Using the resolved `{issue_id}` and the
`{issue_type_id}` from the native-type map:

```
gh api graphql -f query='mutation($issue:ID!,$type:ID!){
  updateIssueIssueType(input:{ issueId:$issue, issueTypeId:$type }){
    issue { id issueType { name } }
  }
}' -F issue='<issue_id>' -F type='<issue_type_id>' \
  --jq '.data.updateIssueIssueType.issue.issueType.name'
```

Read the returned name back to confirm it applied. On error, fall back to
applying the `type-*` label for that issue and report it loudly (the org
claimed to be type-capable but the set failed).

## Step 5 — Populate field values

Set every resolved, applicable field in **one** call. Build the
`issueFields` list from whichever fields Step 2 found and the command has
values for — single-select fields take `singleSelectOptionId` (resolve the
option **name** to its id via the field's option map from Step 2), date
fields take `dateValue: "YYYY-MM-DD"`, text fields take `textValue`.

**Important:** Pass the fields **inline in the mutation string**, not as a
GraphQL variable. The `gh api graphql` CLI serialises `-f fields='[...]'`
as a JSON string, not a list of objects, causing a GraphQL type error.
Build the mutation with the actual field and option IDs substituted in:

```
gh api graphql -f query='mutation {
  setIssueFieldValue(input:{
    issueId:"<issue_id>",
    issueFields:[
      { fieldId:"<priority_field_id>", singleSelectOptionId:"<priority_option_id>" },
      { fieldId:"<classification_field_id>", singleSelectOptionId:"<classification_option_id>" },
      { fieldId:"<effort_field_id>",   singleSelectOptionId:"<effort_option_id>" },
      { fieldId:"<origin_field_id>",   singleSelectOptionId:"<origin_option_id>" }
    ]
  }){
    issue { id }
  }
}' --jq '.data.setIssueFieldValue.issue.id'
```

For a **date field** (Start date, Target date), use `dateValue` instead
of `singleSelectOptionId`. Get today's date with `date -u +%Y-%m-%d` and
substitute it inline:

```
gh api graphql -f query='mutation {
  setIssueFieldValue(input:{
    issueId:"<issue_id>",
    issueFields:[
      { fieldId:"<start_date_field_id>", dateValue:"2026-06-08" }
    ]
  }){
    issue { id }
  }
}' --jq '.data.setIssueFieldValue.issue.id'
```

Include only the fields that apply — omit any field the org does not
define or the command has no value for. For a field the command *intended*
to set but the org does not define, emit the `skipped field 'X' (not found
in org issue fields)` line from Step 2 — distinguish "nothing to set here"
from "this org is missing a field you expected." **Once-per-session
reporting:** if `.claude/issue-fields-cache.json` has `skips_reported:
true`, suppress the skip lines (already emitted this session); otherwise
emit them, then merge `skips_reported: true` into the cache so later
commands suppress them. A `setIssueFieldValue` failure is best-effort:
report it and continue; the issue still exists and still carries its
labels.

**Priority is dual-tracked.** Populate the `Priority` field **and** keep
applying the `priority-*` label. The label keeps the selector's existing
priority sort cheap (no per-issue field read), while the field gives the
GitHub UI and reporting a first-class value. `Classification` and the
native type are **not** dual-tracked on type-capable orgs — the native
type replaces the `type-*` label, and `Classification` is an independent
subcategory field (always set, never blank).

## Step 6 — Selector: filter by kind, with label fallback

`templates/story-selection.md`'s mode filter (`feature` → stories only;
`maintenance` → bug/security/debt/arch) resolves kind through this file:

- **Type-capable org** → read each candidate's native `issueType.name`
  (include it in the `gh issue list`/GraphQL projection) and filter on it
  via the native-type map. No `type-*` label is involved.
- **Not type-capable** → filter on the `type-*` labels exactly as before.

Priority sort continues to read the `priority-*` label (dual-tracked in
Step 5), so selection needs no per-issue field read.

## Step 7 — Native "blocked by" relationship

`block-story` (and optionally `feature-discovery` for known dependency
chains) records a blocker as a native relationship **in addition to** the
body `## Dependencies` markers (which the auto-unblock parser still reads):

```
gh api graphql -f query='mutation($issue:ID!,$by:ID!){
  addBlockedBy(input:{ issueId:$issue, blockedByIssueId:$by }){ clientMutationId }
}' -F issue='<issue_id>' -F by='<blocking_issue_id>'
```

Best-effort: if the relationship API is unavailable, the body markers
remain the source of truth and the workflow is unaffected.
