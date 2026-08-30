# Worked examples

Four issues written to the standard in `SKILL.md`, from the smallest
shape to a larger infrastructure story. Each one shows the title, the
body, and what was deliberately left out.

The title is shown as a heading here so each example reads as one piece.
In a real issue the title goes in GitHub's title field and the body
starts at `## Summary`.

---

## Example 1: Stale comments

### Remove stale accessibility comments

```markdown
## Summary

There are 2 accessibility comments that still describe a prompt asking
the reader whether to jump to a position pulled from another device, but
that prompt no longer exists.

The only case that currently triggers this behaviour is a playback
error. The comments should be updated to reflect the actual behaviour.

## Changes

Update the comments in:

- `src/utils/a11yHidden.ts`
- `src/app/reader/[bookId].tsx`

No behaviour changes are needed.

## Acceptance criteria

- The comments no longer reference a cross-device position prompt.
- The comments describe the playback error that currently triggers the
  behaviour.
- No functional changes.
```

**Left out:** how the stale comments were discovered, the history of the
removed sync implementation, grep results, and a long explanation of the
accessibility trade-off. None of them change what the implementer does.

---

## Example 2: Read-only accessibility labels

### Fix accessibility labels on read-only Settings rows

```markdown
## Summary

Read-only Settings rows with a value are currently read as 2 separate
accessibility elements.

For example, the Version row is read as "Version" and then "1.0.0",
rather than as a single label.

`SettingsRow` already creates the correct accessibility label, but
`ListRow` drops it for non-interactive rows.

## Changes

Update `ListRow` so that non-interactive rows use the supplied
accessibility label.

The local `ReadOnlyRow` workaround in `SubscriptionScreen` can then be
removed.

## Acceptance criteria

- Read-only Settings rows with a value are read as a single
  accessibility element.
- The Version row reads correctly.
- The `SubscriptionScreen` workaround is removed.
```

**Why the cause is here:** it sits in the Summary rather than its own
`## Cause` section because it is one sentence and it tells the
implementer where the fix belongs.

**Left out:** the history of why `SubscriptionScreen` originally used a
workaround.

---

## Example 3: Lock-screen playback

### Fix lock-screen playback progress

```markdown
## Summary

The lock-screen playback timeline is incorrect for recordings and
documents using the fallback playback engine.

- Recordings show the original audio duration rather than adjusting for
  playback speed.
- Fallback documents show the current sentence duration rather than the
  estimated duration of the full document.

Documents using the native Cadence playback engine are not affected.

## Cause

`expo-audio` controls the lock-screen duration and progress from the
underlying audio player and does not currently allow us to override
these values.

## Changes

This will likely need either:

- support for custom duration and progress values in `expo-audio`, or
- the lock-screen values to be managed directly in the native iOS and
  Android implementations.

## Verification

Test on a physical device with:

- A recording at 1x and 2x.
- A document using the fallback engine.
- A document using the native engine to confirm there is no regression.
```

**Why the implementation stays open:** the source does not establish
which approach should be used, so the issue says "will likely need
either" rather than picking one. Do not close an open question the
source left open.

**Why there is a Verification section:** it needs a physical device and
a regression check on the unaffected path, which acceptance criteria
alone would not convey.

---

## Example 4: Larger infrastructure story

Even a larger issue should still start simply.

### Deploy the Cadence API to production and sandbox

```markdown
## Summary

The Cloudflare resources and production API hostname already exist, but
`backend/wrangler.toml` still contains placeholder bindings and does not
have a complete sandbox environment.

Update the configuration, apply the D1 migrations, deploy sandbox first
and then production, and verify both Workers.

## Changes

- Replace the production D1 and KV placeholder IDs with the existing
  Cloudflare resource IDs.
- Add the production route and production environment values.
- Add the full sandbox environment with its own D1, KV, R2, queue and
  DLQ bindings.
- Keep `CADENCE_WEB_ORIGINS` and `CADENCE_COOKIE_DOMAIN` empty.
- Apply the D1 migrations to sandbox first and then production.
- Deploy sandbox first and then production using Wrangler.

## Manual step

The first deploy does not require GitHub App access.

Workers Builds can be configured afterwards for ongoing deployments. An
organisation owner will need to grant the Cloudflare GitHub App access
to `CadenceReader` before that can be enabled.

## Verification

- Both health endpoints respond from the real Workers.
- Production no longer returns the placeholder `503`.
- Both queues have consumers and dead-letter queues.
- The cron trigger exists on both Workers.
- Both D1 databases contain the expected tables.
- Store notification routes continue to fail closed while their
  credentials are unset.

## Out of scope

- Apple and Google private credentials.
- Store product configuration.
- A dedicated API domain.
```

**Left out:** the complete provisioning history, why every resource was
originally created, and each previous limitation that no longer affects
the work.

**Why `## Manual step` is here:** part of the work needs an
organisation owner, so the implementer would otherwise stall on it.

**Why `## Out of scope` is here:** the deploy sits next to credentials
and store configuration, so there is a realistic risk the work expands
into them.

---

## What these examples have in common

- Every one opens with the actual problem in the first sentence.
- None of them uses every section.
- None of them explains the same thing twice.
- The two that keep uncertainty ("will likely need either") keep it in
  the words the source used.
