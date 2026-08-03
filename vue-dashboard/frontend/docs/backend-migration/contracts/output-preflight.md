# Output preflight contract

Status: owner-confirmed contract; endpoint and UI deferred.

## Request

`POST /api/v1/sessions/<session_id>/output-preflight`

```json
{ "expected_session_updated_at": "datetime or null" }
```

The target is a persisted Draft. The backend derives canonical sinks, assignments, parameters, and paths; clients do not submit sink configuration or secrets.

## Response

The response contains `session_id`, `session_updated_at`, `checked_at`, an opaque `preflight_token`, `ready`, per-sink `sinks`, and flattened top-level `warnings` and `blockers`.

Each sink has `source_id`, `sink_name`, `sink_type`, `category`, `requested_location`, `resolved_location`, `checks`, `warnings`, and `blockers`. Sink identity is `(source_id, sink_name)`, never array position.

Each check/result has `{code, severity, message, field}`. Public schema metadata may expose names, required/optional/default/type information, and secret-reference key presence, but never secret values.

`ready` is true exactly when `blockers` is empty.

## Classification

### Blockers

- Invalid or unsupported sink type/public parameter schema.
- Missing required parameter or secret reference.
- Unavailable selected dependency.
- Invalid, escaping, unresolved, or non-file output path where a file is required.
- Known unwritable parent/root.
- Existing collision for a non-overwrite start.
- Known insufficient free space.

### Warnings

- Optional parameter omitted/defaulted.
- Missing parent with writable existing ancestor.
- Unknown free-space or writability state.
- Storage above warning threshold but not known insufficient.
- Indeterminate dependency readiness requiring destructive/network probing.
- Automatically resolved/default output path or suggested collision-free alternative.

## Safe no-write probes

Allowed: parse/normalize config, lexical path resolution, stat existing paths/ancestors, access metadata, disk usage, import availability, and presence (not value) of configured secret references.

Forbidden: creating/deleting/renaming/opening files or directories for write, reserving names, truncating outputs, mutating Draft/config/claims, claiming devices, persisting operations, exposing secrets, destructive dependency probes, and external network writes.

## Staleness and Start

The browser marks preview stale when `session_updated_at` or any draft assignment, sink, or output field changes. A future Start request may carry `preflight_token`, but the server reruns authoritative preflight inside the guarded Start workflow.

Stale revision/token returns `409 preflight_stale` with the current result and creates no operation. Current blockers return `409 preflight_blocked` with typed blockers/current result and preserve the Draft. Warnings alone do not block Start unless a later product rule requires acknowledgement.

## Handoff

This packet intentionally implements no endpoint or UI. Backend/API/UI implementation requires a fresh work-packet breakdown.
