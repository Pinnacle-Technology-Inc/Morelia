# v1 Session duplication contract

Status: accepted 2026-07-22; implementation intentionally deferred to a future packet.

## Result and copied fields

Duplication always creates a new `Draft` session with a new session id, request/result identity, and no runtime generation. It copies name (through a conflict-safe suggested suffix), policy, schedule defaults, experiment association when still valid, and canonical device-flow composition/sink parameters. It never copies `status`, command/runtime/watchdog/dataflow ids, claims, operations, incidents, gaps, recovery history, output ids, generated paths, or secrets.

Generic copy strips `device_config_id`, `hardware_id`, `port`, claims, and every physical identity. It retains canonical device-template/type requirements, nickname, ordered sinks, public sink parameters, and explicit user-entered non-generated locations only where safe; generated/resolved output paths are cleared. `Copy device identity` retains `device_config_id`, type, and hardware id only as draft intent; it never claims hardware. Planner and Start revalidate, and unavailable/claimed devices block Start while leaving the Draft editable.

The copied experiment association is retained only when valid and non-archived. Schedule is reset to manual with no `start_at`. Missing or archived source experiments are cleared and reported as a warning. Suggested names are `<source name> Copy`, then `<source name> Copy (2)`, etc.; explicit conflicts return 409.

## API and failures

`POST /api/v1/sessions/<id>/duplicate` accepts `{name?, mode, experiment_id?, request_key}` where mode is `generic` or `device-identity`. It returns `201` with the new Draft and a bounded assignment summary. `request_key` is required; identical key/payload returns the original result without another Draft, mismatched reuse returns 409 `request_key_conflict`. Problems include source-not-found, invalid-mode, name-conflict, and device-reassignment-required. The operation is atomic: no partial Draft is visible.

The dialog maps its two current modes to this contract and must state that no runtime/history/output identity is copied. A fresh work-packet breakdown must define exact model/API/UI files before implementation.
