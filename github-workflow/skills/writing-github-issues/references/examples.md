# Worked examples

These examples show the expected level of detail. The goal is to keep only what helps someone understand, implement or verify the issue.

---

## 1. Small issue

### Title

Remove stale accessibility comments

### Body

```markdown
## Summary

There are 2 accessibility comments that still describe a prompt asking the reader whether to jump to a position pulled from another device, but that prompt no longer exists.

The only case that currently triggers this behaviour is a playback error.

## Changes

Update the comments to describe the playback error instead. No behaviour changes are needed.

## Acceptance criteria

- The comments no longer reference a cross-device position prompt.
- They describe the playback error that currently triggers the behaviour.
- No functional changes.
```

Left out: discovery history, grep results, removed sync history and a long explanation of the accessibility trade-off.

---

## 2. Known cause

### Title

Fix accessibility labels on read-only Settings rows

### Body

```markdown
## Summary

Read-only Settings rows with a value are currently read as 2 separate accessibility elements.

For example, the Version row is read as "Version" and then "1.0.0", rather than as one label.

`SettingsRow` creates the correct accessibility label, but `ListRow` drops it for non-interactive rows.

## Changes

Update `ListRow` so non-interactive rows use the supplied accessibility label. Remove the local workaround in `SubscriptionScreen`.

## Acceptance criteria

- Read-only Settings rows with a value are read as one accessibility element.
- The Version row reads correctly.
- The local workaround is removed.
```

Left out: why the workaround was originally added and the investigation used to locate the cause.

---

## 3. Open implementation choice

### Title

Fix lock-screen playback progress

### Body

```markdown
## Summary

The lock-screen playback timeline is incorrect for recordings and documents using the fallback playback engine.

- Recordings show the original duration instead of accounting for playback speed.
- Fallback documents show the current sentence duration instead of the full-document estimate.

Documents using the native playback engine are not affected.

## Cause

`expo-audio` controls the lock-screen duration and progress and does not currently allow these values to be overridden.

## Changes

This will likely need either:

- support for custom duration and progress values in `expo-audio`, or
- native iOS and Android handling for the lock-screen values.

## Verification

Test on a physical device with:

- A recording at 1x and 2x.
- A fallback-engine document.
- A native-engine document to confirm no regression.
```

Left out: investigation history and implementation detail that does not help choose between the 2 approaches.

The implementation stays open because the source does not establish which approach should be used.

---

## 4. Larger infrastructure story

### Title

Deploy the Cadence API to production and sandbox

### Body

```markdown
## Summary

The Cloudflare resources and production API hostname already exist, but the backend configuration still contains placeholder bindings and does not have a complete sandbox environment.

Update the configuration, apply the database migrations, deploy sandbox first and then production, and verify both environments.

## Changes

- Replace the production placeholder resource IDs.
- Add the production route and environment values.
- Add the complete sandbox environment with separate resources.
- Keep the web origins and cookie domain empty.
- Apply migrations to sandbox first, then production.
- Deploy sandbox first, then production.

## Manual step

An organisation owner must grant the Cloudflare GitHub App access before automatic GitHub deployments can be enabled. This is not required for the first manual deploy.

## Verification

- Both health endpoints respond from the real Workers.
- Production no longer returns the placeholder `503`.
- Both environments have the expected database schema and queue configuration.
- Store notification routes continue to fail closed while credentials are unset.

## Out of scope

- Apple and Google private credentials.
- Store product configuration.
- A dedicated API domain.
```

Left out: provisioning history, resource-by-resource background and previous limitations that no longer affect the work.

---

## Pattern

All 4 examples:

- Start with the actual problem.
- Use only the sections that add information.
- Keep uncertainty when the source is uncertain.
- Remove investigation history and proof of work.
- Avoid repeating the same point in multiple sections.
