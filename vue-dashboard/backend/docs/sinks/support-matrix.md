# All-sink support matrix

**Status:** shipped contracts as of packet 30 closeout (2026-07-21).  
**Authorities:** [`README.md`](README.md) (invariants + packet graph),
[`../all-sink-support-design-and-gap-audit.md`](../all-sink-support-design-and-gap-audit.md)
(historical design/gap), [`IMPLEMENTATION-STATUS.md`](IMPLEMENTATION-STATUS.md)
(execution evidence), [`operator-runbook.md`](operator-runbook.md) (ops).

Do **not** treat the design audit as an operator runbook. This matrix is the
verified support statement. Capabilities without packet-30 evidence are marked
explicitly.

## Global rules (every sink)

| Rule | Behavior |
|---|---|
| Cardinality | One source owns an ordered non-empty `sinks[]`; each sink belongs to exactly one source. Repeated types allowed when `sink_name` / `sink_id` is unique within the source. |
| Contract | Writers emit nested multi-sink. Readers accept legacy flattened inbound and normalize immediately. |
| Health | Source/stream health and per-sink health are separate axes. A sink failure must not masquerade as source recovery. |
| Secrets | Only a runtime worker may resolve Influx credentials. Tokens never enter config, manifests, logs, reports, templates, or status. |
| Stop vs error | User stop completes the acquisition. Error recovery may continue the same acquisition (linked file components). A later start always allocates new output identity. |
| Outboxes | `SinkDeliveryOutbox` = raw service-sink delivery only. `WatchdogOutbox` = telemetry only. Never overload them. |

## Per-sink matrix

| Sink | Category | Dependencies | Startup policy | Recovery policy | Buffering / loss | Finalization | CI evidence | Hardware evidence | Known limits |
|---|---|---|---|---|---|---|---|---|---|
| **CSV** | file | none (stdlib) | Require resolved `file_path`; deferred-open managed writer | Append-only reopen of same path; never truncate | N/A (durable file) | Single-component: `not_required` | Hermetic managed-CSV + factory + multi-sink stack | Pod8206HR/8401HR first-start/stop (opt-in `RUN_HARDWARE`) | Truncated final CSV row possible on hard kill (reported) |
| **EDF** | file | `pyedflib`, `numpy` | Preflight/doctor probe; fail start if missing | Always linked continuation (`B`, `B_1`, …); prior bytes immutable | N/A | Multi-component → merge_pending → format-aware merge → `merged`; components retained on failure | Packet 14/17 + release gate EDF merge sample-order | Pending matrix capture on target FS | Mid-record interrupt zero-pads to record boundary (appears in merge) |
| **PVFS** | file | `pvfs_tools` (native; Win/Linux) | Preflight/doctor; fail if missing/unsupported OS | Linked continuation like EDF | N/A | Format-aware merge in short-lived child (Windows rename) | Packet 15/18 hermetic where native available | Pending; writer-process + high-rate lane | Never rename/unlink a container from a process that opened it |
| **Influx** | service | `influxdb-client` (+ extras group) | Fail start if deps/secret/env/destination unreadiness | Reconnect; replay `SinkDeliveryOutbox` in order | Age + per-sink byte + global disk caps; drop **oldest**; exact loss counters | N/A (no file merge) | Outbox bounds/replay gates; adapter unit tests | Disposable Influx allowed in CI; no disposable run in packet-30 closeout | `api_token_env` only — never paste tokens |
| **Quest** | service | Quest ILP TCP client deps | Fail start if deps/host unreadiness | Same outbox reconnect/replay model as Influx | Same age/byte/global bounds + oldest-drop | N/A | Outbox gates + Quest adapter tests | Disposable QuestDB allowed; not run in packet-30 closeout | No secrets in parameters |
| **Plot** | live presentation | none (browser SSE) | Builds without native deps; no Qt | Browser reattach via cursor; acquisition never blocked | Producer rate-decimation + per-subscriber drop-oldest queues; explicit `dropped` | N/A | Packet 27/28 + release Plot lag gate | Dashboard sustained run pending | Live path needs `plot_transport` wiring + token mint HTTP (integrator); without them: drop-mode / Unauthorized |

### Evidence legend

| Label | Meaning |
|---|---|
| Hermetic / CI-proven | Automated tests under `tests/test_*.py` (non-hardware) green for that contract |
| Hardware-proven | `RUN_HARDWARE=1` + Pod checkpoint with `sink_matrix` evidence |
| Preview / experimental | Contract exists; end-to-end production path incomplete (see Known limits) |
| Pending | Required for advertising production-ready; not yet recorded |

## Compatibility path

1. **Readers before writers:** v1+v2 manifest readers remain; new writers emit v2 `sinks[]`.
2. **CSV default unchanged** for single-CSV sessions; multi-sink is additive.
3. **Doctor / preflight** report per-selected-sink capability; unavailable sinks block start with an actionable reason without mutating requested type.
4. **Rollback:** disable creation of new non-CSV sinks; retain v2 read/stop/recovery. Never deploy a binary that cannot read persisted v2 manifests.

## Release evidence (packet 30)

| Gate | Result (2026-07-21) |
|---|---|
| `tests/test_multi_sink_runtime.py` + `tests/test_service_sink_outages.py` | **11 passed** |
| Broad suite (ignore broken `test_device_templates.py`, ignore `tests/hardware/`) | **958 passed, 44 failed** (pre-existing CLI/template/supervision drift; not packet-30 files) |
| Hardware multi-sink matrix | Documented; **not run** this closeout |

## Unresolved limitations (do not advertise around these)

1. `RuntimeContext.plot_transport` still `None` in `morelia.py` → Plot runs bounded drop-mode until wired.
2. No HTTP `mint_plot_token` route → Vue needs `token` prop / `VITE_PLOT_STREAM_TOKEN`.
3. `tests/test_device_templates.py` collection ImportError (`get_by_id`).
4. 44 full-suite failures outside sinks edit sets (CLI device-template / host supervision).
