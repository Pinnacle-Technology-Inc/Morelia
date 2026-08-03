# CLI → HTTP contract

Mapped from the live CLI (`app/cli/*`) and Flask routes (`app/api/*`).
Base URL is the daemon (typically `http://127.0.0.1:5000`).

## Daemon lifecycle

| CLI | HTTP / behavior |
|---|---|
| `pinnacle start` | **Local only** — spawn daemon process (no API call) |
| `pinnacle status` | **Local only** — pid file + TCP probe of serving URL |
| `pinnacle shutdown [--force]` | `POST /api/v1/runtimes/shutdown` `{force}` then kill pid; untracked daemon: `POST /api/v1/runtimes/control-plane-shutdown` `{force}` |
| `pinnacle doctor` | Mostly **local** diagnostics; daemon probe: `GET /openapi.json` |

## Devices

| CLI | HTTP |
|---|---|
| `pinnacle device list` | `GET /api/v1/devices/pool` |
| `pinnacle device template validate <file>` | **Local only** (offline validation) |
| `pinnacle device template import <file>` | `POST /api/v1/device-templates` |
| `pinnacle device template list` | `GET /api/v1/device-templates` |
| `pinnacle device template show <name>` | `GET /api/v1/device-templates/{name}` |
| `pinnacle device template edit <name>` | `GET` then `PUT /api/v1/device-templates/{name}` |
| `pinnacle device template rename <name> <new>` | `POST /api/v1/device-templates/{name}/rename` `{new_name}` |
| `pinnacle device template delete <name>` | `DELETE /api/v1/device-templates/{name}` |
| `pinnacle device template export <id\|nick> <output>` | `GET /api/v1/device-configs/{id}` → then `POST /api/v1/device-templates` (or write file locally) |
| `pinnacle device config` | `POST /api/v1/device-configs` (+ often `GET /api/v1/devices/pool` for port) |
| `pinnacle device config --template …` | `POST /api/v1/device-configs/from-template` |
| `pinnacle device edit <device-id>` | `PATCH /api/v1/device-configs/{id}` |
| `pinnacle device delete <device-id>` | `DELETE /api/v1/device-configs/{id}` |

## Sessions

| CLI | HTTP |
|---|---|
| `pinnacle session list` | `GET /api/v1/sessions/overview` |
| `pinnacle session create` | `POST /api/v1/sessions/` (CLI also reads configs/pool/templates while prompting) |
| `pinnacle session create --template …` | `GET /api/v1/session-templates/{name}` → `POST …/assignment-plan` → `POST /api/v1/sessions/` |
| `pinnacle session validate <file>` | **Local only** |
| `pinnacle session preview <file>` | **Local only** |
| `pinnacle session start <id>` | `POST /api/v1/sessions/{id}/commands/start` `{sink_overrides?, force?}` |
| `… --wait` | poll `GET /api/v1/operations/{operation_id}` |
| `… --watch` (default) | then `GET /api/v1/sessions/{id}/events` (SSE) |
| `pinnacle session status <id>` | `GET /api/v1/sessions/{id}/status` |
| `pinnacle session watch <id>` | `GET /api/v1/sessions/{id}/events[?after=N]` (SSE) |
| `pinnacle session stop <id>` | `POST /api/v1/sessions/{id}/commands/stop` `{force?}` |
| `pinnacle session recover <id> --device … --action …` | `POST /api/v1/sessions/{id}/commands/recover` `{device_id, action}` |
| `pinnacle session template export <id> <name>` | `POST /api/v1/sessions/{id}/template-export` `{name, binding_mode}` *(path export is local, no HTTP)* |

## Operations / incidents / gaps / runtimes

| CLI | HTTP |
|---|---|
| `pinnacle operation list` | `GET /api/v1/operations/?session=&state=&dataflow=` |
| `pinnacle operation show <id>` | `GET /api/v1/operations/{operation_id}` |
| `pinnacle operation resolve <id> --outcome … --note …` | `POST /api/v1/operations/{operation_id}/resolve` `{outcome, resolved_by, resolution_note}` |
| `pinnacle incident list --session <id>` | `GET /api/v1/incidents?session={id}` |
| `pinnacle incident show <id>` | `GET /api/v1/incidents/{incident_id}` |
| `pinnacle incident ack <id> --note …` | `POST /api/v1/incidents/{incident_id}/ack` `{note?, acknowledged_by?}` |
| `pinnacle gap list --session <id>` | `GET /api/v1/gaps?session={id}` |
| `pinnacle runtime list` | `GET /api/v1/runtimes/` |
| `pinnacle runtime reconcile` | `POST /api/v1/runtimes/reconcile` |
| `pinnacle runtime command list/show` | **Not implemented** — no CLI and no `/api/v1/...` route yet |

## Review files

- CLI: `vue-dashboard/backend/app/cli/{lifecycle,doctor,device_cmd,session_cmd,operation_cmd,incident_cmd,gap_cmd,runtime_cmd}.py`
- HTTP: matching modules under `vue-dashboard/backend/app/api/*.py`
