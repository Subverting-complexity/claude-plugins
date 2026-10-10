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
