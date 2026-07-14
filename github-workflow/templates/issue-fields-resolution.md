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

## Session cache

Steps 1 and 2 each make a GraphQL round-trip to discover org capabilities.
In multi-issue sessions (audit mode, `feature-discovery` breakdowns) those
calls — and the "skipped field 'X'" messages — would otherwise repeat per
issue rather than once per session.

Cache both results in `.claude/issue-fields-cache.json`. Each step checks for
its own key before querying, then merges its results into the file on a cache
miss. Steps 1 and 2 are independent — the file may hold only one key if only
one step has run so far. The `execute` skill's "Exit cleanup" deletes this file
alongside the other `.claude/` scratch files.

Cache keys:

| Key | Set by | Value |
| --- | ------ | ----- |
| `type_capable` + `type_map` | Step 1 | boolean + `{name, id}` array |
| `field_map` | Step 2 | `{name, id, options}` array |
| `skips_reported` | Step 5 | `true` after the first emission of skip messages |

To check for a key: parse `.claude/issue-fields-cache.json` and test whether
the key is present. To write (merge, not overwrite): read the file if it
exists, update the dict, write it back. Use `python3`, `py -3`, or `python`
(whichever is available) for the JSON read-merge-write. If none runs (no
Python on this machine), **skip the cache write** and proceed with the
freshly-resolved values, noting once "field cache skipped: no Python
available" — the cache is an optimisation; never fail the workflow over it.

## Step 1 — Discover native issue types (capability gate)

List the org's enabled issue types and map each **name** to its node id:

**Session cache check.** If `.claude/issue-fields-cache.json` contains
`type_capable`, read `type_capable` and `type_map` from it and skip the
query below. On a miss, run the query then merge both keys into the cache
file (preserving any existing keys, such as a prior Step 2's `field_map`).

```
gh api graphql -f query='query($login:String!){
  organization(login:$login){
    issueTypes(first:20){ nodes { id name isEnabled } }
  }
}' -F login='{org}' \
  --jq '[.data.organization.issueTypes.nodes[] | select(.isEnabled) | {name, id}]'
```

- **Returns one or more enabled types** → the org is **type-capable**.
  Build a name→id map (`Bug`, `Feature`, `User Story`, `Epic`). Native
  types are now the **authoritative** classification; do **not** also
  apply the `type-*` label (the native type renders in the issues list on
  its own). The selector filters by native type (Step 5).
- **Errors, returns empty, or the owner is a user account** (the
  `organization` field is null — issue types are an org-only feature) →
  the org is **not type-capable**. Fall back to today's behaviour
  unchanged: classify with the `type-*` labels from
  `templates/default-labels.md` and filter on those labels. Skip every
  native-type step below; never treat the absence of native types as an
  error.

Resolve the workflow's kind → native type through the **native-type map**
in `templates/default-labels.md` (the "by nature" default). When a mapped
type name is not in the discovered set, fall back to the `type-*` label
for that one issue and note it.

## Step 2 — Discover org issue fields (per-field capability gate)

List the org's issue fields with their options. **Use the GraphQL query
below, not the REST endpoint** — REST (`/orgs/{org}/issue-fields`) returns
`null` for all option IDs, making single-select fields unusable:

**Session cache check.** If the cache contains `field_map`, read it and
skip the query. On a miss, run the query then merge `field_map` into the
cache file (preserving any existing keys).

```
gh api graphql -f query='query($org:String!){
  organization(login:$org){
    issueFields(first:20){
      nodes {
        ... on IssueFieldSingleSelect {
          id name
          options { id name }
        }
        ... on IssueFieldDate {
          id name
        }
        ... on IssueFieldText {
          id name
        }
      }
    }
  }
}' -F org='{org}' \
  --jq '[.data.organization.issueFields.nodes[] | select(. != null) | {name, id, options}]'
```

Build a name→`{id, options}` map (for single-select fields, `options` is a
list of `{name, id}` pairs with real node IDs). Each field is gated
**independently**: populate only the fields the org actually defines, and
skip any that are absent. An org defining none of these fields creates
issues exactly as today (labels only) — a valid configuration, not a
failure.

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

Resolve a field's purpose to its concrete name through `ClaudeProject.md`
→ `## Issue Types & Fields` (defaults in `templates/default-labels.md`):

| Purpose key      | Default field name | Type          | Set by |
|------------------|--------------------|---------------|--------|
| `field-priority` | `Priority`         | single-select | report-issue, execute, feature-discovery |
| `field-effort`   | `Effort`           | single-select | every issue-creating command |
| `field-type`     | `Classification`   | single-select | every issue-creating command |
| `field-origin`   | `Origin`           | single-select | every issue-creating command |
| `field-start`    | `Start date`       | date          | execute (on claim) |
| `field-target`   | `Target date`      | date          | execute (on PR creation — records actual completion date) |
| `field-parent`   | `Parent`           | text          | feature-discovery (epic-child link) |
| `field-status-reason` | `Status reason` | text         | block-story (blocker description) |

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
