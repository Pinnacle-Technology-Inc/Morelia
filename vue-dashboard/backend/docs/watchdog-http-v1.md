# Watchdog localhost HTTP/JSON contract — v1

Flask is the client and each Watchdog process is a localhost-only HTTP server.
The URL version and JSON protocol version must both be present:

`POST http://127.0.0.1:<port>/api/v1/commands`

Headers:

- `Content-Type: application/json`
- `Accept: application/json`

## Command request schema

```json
{
  "protocol_version": "1",
  "command": "start | stop | restart-all-streams | reconnect | restart | reset-stream",
  "target_device_id": "optional non-empty string",
  "correlation": {
    "request_id": "non-empty string",
    "session_id": "non-empty string",
    "dataflow_id": "non-empty string",
    "command_id": "non-empty string",
    "watchdog_id": "non-empty string",
    "recovery_id": "optional non-empty string"
  }
}
```

All fields shown are required except `recovery_id` and `target_device_id`.
Unknown fields and any protocol version other than `"1"` are rejected.

`target_device_id` names one device→sink stream (one StreamWatcher) within the
dataflow. Recovery commands (`reconnect` / `restart` / `reset-stream`) act on a
single stream at a time, so they carry both a `recovery_id` (the episode that
rides every report — spec line 128) and a `target_device_id`. Whole-dataflow
commands (`start` / `stop` / `restart-all-streams`) omit `target_device_id`.
`restart-all-streams` still requires `recovery_id` because it creates one
dataflow-wide recovery episode. The agent rejects a recovery command that omits
the target, omits the recovery id, or names a device its manifest does not own.

## Accepted response schema

HTTP status: `202 Accepted`

```json
{
  "protocol_version": "1",
  "status": "accepted",
  "command_id": "same command_id as the request",
  "watchdog_id": "same watchdog_id as the request"
}
```

Every response field is required. Unknown fields, malformed JSON, a non-JSON
content type, mismatched identifiers, oversized bodies, unsupported protocol
versions, and non-202 statuses fail closed. Flask does not mutate command or
session state until this acknowledgement validates.

## Failure mapping

| Boundary failure | Flask API response |
| --- | --- |
| Connection refused/unavailable | `503`, code `watchdog_unavailable` |
| Request timeout | `504`, code `watchdog_timeout` |
| Malformed or unsupported response | `502`, code `watchdog_invalid_response` |

Backend tests inject `FakeWatchdogAdapter`; they do not open a socket or require
Morelia hardware.
