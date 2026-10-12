# Pull request body examples

Note the line breaks in these: each paragraph and each bullet is one line, however long.

## Example 1: Standardizing service generation

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
- Removed the 4 unused report strategies, such as `NonBillableReportStrategy`
- Removed `importantInformation` from method signatures and the internal logic behind it

### Client validation

- Removed `CreateInformationMessage` and its RTF rendering logic
- `ValidateClients` now logs directly and returns `void`

## Test plan

- `dotnet test` passes, including the report-generation suite
- Generated a weekly and a monthly report against sample data and diffed them against the previous build: identical output

Closes #412
```

---

## Example 2: Service provider discount support

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

- Added 3 client discount config fields, led by `DiscountFactor`
- Added validation: only one default discount, a named service provider must exist, and no duplicate discounts per service provider

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

## Example 3: A small change

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

---

## Example 4: A large change

A change that adds a whole feature across the database, the API and the front end. The body describes what users and reviewers get, in capabilities and rules. It does not list the 9 entities, 6 commands and 5 components that the diff adds.

**Title block:**
```
Add the report templates setup page
```

**Description block:**
```markdown
## Summary

Adds a setup page where users keep the templates, rules and profiles that the report generator uses. Templates and rules are versioned, and a profile links a set of accounts to one template and an ordered list of rules. This pull request merges into `feature/report-overview`.

## Changes

### Access

- Added a `Reports` role and a policy that lets `Reports` and `Admin` users manage templates. The policy guards the API, the page route and the menu entry
- The profile page reads accounts through the setup API, because the general accounts API needs a stronger permission

### Data and versions

- Added storage for templates, rules and profiles. Every save of a template or rule adds a numbered version, and old versions are never edited
- A profile follows the current version of its template and rules, not a fixed one
- Two people saving at the same time cannot overwrite each other: the second save gets a "reload and try again" message
- Only one profile can be the default
- Added migration `AddReportTemplates`

### Archive

- Nothing is deleted. Users archive and restore templates, rules and profiles, and archived items are read-only
- A template or rule that an active profile uses cannot be archived, and the message names those profiles. The default profile cannot be archived

### Rule documents

- A user uploads a PDF, and the service converts it to Markdown with OpenAI so tables keep their layout. The user checks the result beside the PDF, edits it, and saves
- The PDF goes to external storage and the checked Markdown goes to the database. If the save fails, the uploaded PDF is deleted
- A document that is in use cannot be removed. It is withdrawn from the rule instead
- A new admin-only setting chooses the storage container for these documents. A container that holds documents cannot be deleted or moved

### Setup page

- Added Profiles, Policies, Prompts and an admin-only Storage tab, with a checklist of the 4 setup steps
- One Save stores the details and, when the content changed, the next version. The page warns before the user leaves with unsaved changes

## Test plan

- `dotnet test` and `npm test` pass, including new tests for versioning, concurrent saves, archive rules and document storage
- Created a template, a rule with an uploaded PDF and a profile in a local environment, archived and restored each, and confirmed the profile page enforces the requirements checklist
```
