---
name: pr-description
description: "Write, format, or structure a Pull Request description from committed changes or rough notes. Works with any platform (GitHub, GitLab, Azure DevOps, Bitbucket). Use when the user wants to document a PR, summarize a branch, or turn change notes into a structured PR. Do NOT use for reviewing code quality (use code-review) or writing user stories (use user-story)."
---

# PR Description Skill

The entry point for **pull request titles and bodies**. It is one of two entry points over `_shared/body-standard.md`, which is the single standard for every body this plugin writes into a tracker or forge. Read that file first. This one adds only what is specific to a pull request.

The counterpart entry point is `writing-github-issues` (github-workflow only), which does the same job for issue bodies. An issue and a pull request are written the same way on purpose: same wording, same section names, same no-wrapping rule.

`_shared/banned-patterns.md` applies in full. `skills/user-facing-communication/SKILL.md` shapes what you say to the person **around** the description: lead with the outcome and the current state, keep it short, surface anything outstanding or assumed. It governs your reply, not the description.

---

## The body

Three sections, these names, this order, on every pull request:

```markdown
## Summary

## Changes

## Test plan
```

Do not rename them, reorder them, merge them, or add a top-level section in their place. A reviewer opening any pull request should find the same three headings in the same order every time.

Two additions are allowed, and only when they carry information:

| Extra section | Add it when |
| ------------- | ----------- |
| `## Manual step` | The change is not complete until a person does something the reviewer cannot do, such as granting access, running a migration or setting a secret. Say exactly what, and why it could not be automated. |
| `## Quality gate failed` | The caller says the quality gate failed. It is the one section that goes **above** `## Summary`, and it carries the last error output. |

Where the platform links issues, the closing keywords go at the very end of the body, under no heading, one line per issue:

```
Closes #42
```

### Summary

Two to four plain-English sentences on the goal, the approach and the impact, written so a reviewer who has not seen the diff or the originating conversation can follow it. Include it always; on a one-line typo fix, one sentence is enough.

### Changes

Bullets, following the bullet rules in `_shared/body-standard.md`. Group them under `###` sub-headings named after the component, module, service or file group only when the change touches more than three separate areas.

### Test plan

How the change was verified, as bullets: the commands run, the tests added or updated, and anything checked by hand. Say plainly if part of it is unverified.

Only leave this section out when there is genuinely nothing to run and nothing to check.

---

## Output structure

When the user asks for a description rather than having one posted for them, return two separate, independently copyable markdown blocks.

**Block 1 — Title.** A code block containing only the title, so it copies cleanly into the title field. Title rules are in `_shared/body-standard.md`.

**Block 2 — Description body.** A code block containing the full body in markdown.

---

## Examples

Note the line breaks in these: each paragraph and each bullet is one line, however long.

### Example 1: Standardizing service generation

**Title block:**
```
Standardize service generation return types and clean up strategies
```

**Description block:**
```markdown
## Summary

Report generation had drifted into a mix of return types and a set of one-off strategy classes that were no longer used. This change makes every generation function return `void` or `Task` so callers handle them consistently, and removes the dead strategies and the `importantInformation` plumbing they relied on. The result is a smaller, more predictable report-generation surface, with no behavioural change for the reports that are still produced.

## Changes

### Report generation service

- All service generation functions now return `void` or `Task`
- Removed `ExtravagantHoursReportStrategy`, `NoCommentReportStrategy`, `NonBillableReportStrategy`, and `ContractorPaymentReportStrategy`
- Removed `importantInformation` from method signatures and the internal logic behind it
- Cleaned unused namespaces: `TimeSync.Strategies.AuditStrategies.Exceptions`, `TimeSync.Strategies.ReportStrategies.Contractor`

### Client validation

- Removed `CreateInformationMessage` and its RTF rendering logic
- Refactored `ValidateClients`: removed `importantInformation`, converted to direct logging, adjusted the return type to `void`

## Test plan

- `dotnet test` passes, including the report-generation suite
- Generated a weekly and a monthly report against sample data and diffed them against the previous build: identical output

Closes #412
```

---

### Example 2: Service provider discount support

**Title block:**
```
Add configurable service provider discounts for invoice line items
```

**Description block:**
```markdown
## Summary

Clients need to be able to give per-service-provider discounts on invoice line items, which the current invoice generation cannot express. This change adds configurable discount fields to the client config, applies them during invoice generation so that a service-provider-specific discount overrides a client-wide one, and adjusts audit generation so the new negative line items do not distort the hour totals.

## Changes

### Configuration

- Added client discount config fields: `DiscountFactor`, `DiscountLineItemDescription`, `ServiceProvider`
- Added validation: only one null entry allowed, `ServiceProvider` must match `Client.ServiceProviders.Name` or be null, no duplicate discounts per service provider

### Invoice generation

- Applied discount logic conditionally, so a service-provider-specific discount overrides a client-wide one
- Falls back to appending the service provider name when `DiscountLineItemDescription` is missing

### Audit generation

- Excluded negative line items from audit calculations, so the hour totals stay correct

## Test plan

- Added unit tests for the validation rules and for the precedence between service-provider and client-wide discounts
- `dotnet test` passes
- Generated an invoice and its audit for a client with both discount kinds configured, and confirmed the audit hours were unchanged

Closes #388
```

---

### Example 3: A small change

**Title block:**
```
Fix accessibility labels on read-only Settings rows
```

**Description block:**
```markdown
## Summary

Read-only Settings rows with a value were read as two separate accessibility elements, so the Version row announced "Version" and then "1.0.0" instead of one label. `SettingsRow` was building the right label all along, but `ListRow` dropped it for non-interactive rows. This change keeps the supplied label on those rows and removes the local workaround that had been papering over it.

## Changes

- Updated `ListRow` to use the supplied accessibility label on non-interactive rows
- Removed the local workaround in `SubscriptionScreen`

## Test plan

- `npm test` passes
- Checked the Settings screen with VoiceOver on an iPhone and TalkBack on a Pixel: each read-only row now reads as one element

Closes #96
```
