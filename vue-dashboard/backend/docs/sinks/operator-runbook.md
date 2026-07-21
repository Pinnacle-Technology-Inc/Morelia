# All-sink operator runbook

Companion to [`support-matrix.md`](support-matrix.md). For design history see
[`../all-sink-support-design-and-gap-audit.md`](../all-sink-support-design-and-gap-audit.md).

## 1. Configure sinks (session / template / quiz)

- Prefer nested `sinks[]` with unique `sink_name` per source.
- Legacy flattened `sink_type` / `sink_location` is still **accepted on read** and
  normalized; new writers should not emit flattened-only forms.
- File sinks (CSV/EDF/PVFS) may use `sink_location` / `file_path`.
- Service and Plot sinks **reject** `sink_location` (wrong category).
- Templates round-trip full sink parameters; guided CLI create can add/edit sinks
  (`pinnacle session create` quiz).
- Validate with doctor / preflight before start:
  `pinnacle doctor` and session start preflight only check **selected** sinks.

## 2. Credentials (Influx)

- Store **`api_token_env`** = environment variable *name* (e.g. `PINNACLE_INFLUX_TOKEN`).
- Set the secret in the **watchdog/worker process environment**, never in TOML,
  DB, manifests, logs, status JSON, or templates.
- If the env var is missing at start → start fails closed with an actionable error.
- Quest has no token field; configure `host` / `port` / measurement only.

## 3. Preflight / doctor failures

| Symptom | Likely cause | Action |
|---|---|---|
| Sink type unknown | Typo / outdated client | Fix type to one of csv/edf/pvfs/influx/quest/plot |
| Missing import / extra | Optional dependency group not installed | Install extras; re-run doctor |
| Influx unreadiness | Bad URL / org / bucket / token env | Fix env + destination; do not paste token into config |
| PVFS unavailable | Native lib / wrong OS | Use supported platform or remove PVFS from selection |
| Blocked session | Selected sink unavailable | Keep requested type; fix dependency — do not silently rewrite to CSV |

## 4. Sink degradation and loss (services)

After a successful start, Influx/Quest outages:

1. Warn immediately on the **per-sink** health axis (source may stay healthy).
2. Buffer raw lines in `SinkDeliveryOutbox` (age + byte + global disk caps).
3. On overflow, **drop oldest** and increment durable loss counters.
4. On reconnect, replay pending in order and ack.
5. Telemetry `WatchdogOutbox` is unrelated — do not look there for sample replay.

Operator view: session status API / CLI sink status show sink rows separately from
`devices[]` stream health.

## 5. EDF / PVFS components and merge

- Error recovery creates linked continuation files (`B`, `B_1`, …). Prior component
  files must remain byte-stable.
- User **stop** marks acquisition `complete`, schedules merge if multi-component,
  and returns **without waiting** for merge.
- Finalizer process owns merge only (no hardware leases). Success → one verified
  published artifact + `artifact_state=merged`. Failure retains components.
- Immediate later **start** on the same hardware allocates a **new** logical/physical
  identity even while prior merge is pending.

## 6. Plot troubleshooting

| State | Meaning | Operator action |
|---|---|---|
| Connecting / Reconnecting | SSE opening or backoff | Wait; check network |
| Live | Batches flowing | None |
| Dropped samples | Subscriber lag; oldest frames discarded | Reduce channels/rate or improve client; acquisition continues |
| Stale | Reconnect budget exhausted; last frame kept | Manual Reconnect in UI |
| Unauthorized | Missing/wrong/cross-scope token | Supply session/sink-scoped token (`mint_plot_token` / env) |
| Stopped | Session stopped or panel unmounted | Expected after navigate-away |

Stream URL:
`GET /api/v1/sessions/<session_id>/plot/<sink_id>/stream?token=…&after=<seq>`

Schema: `plot.samples.v1`. Cursor reconnect uses `after` / `Last-Event-ID`.

If the panel never leaves Unauthorized and no live samples appear on a running
session, check integrator follow-ups: worker `plot_transport` wiring and HTTP
token mint (see support matrix limitations).

## 7. Stop and restart

1. `session stop` → writers close → acquisition `complete` / termination `clean`.
2. Eligible EDF/PVFS merges enqueue; stop does not block on them.
3. Next `session start` → new acquisition, new paths, new outbox keys.
4. Never append to a completed acquisition; never wait on unrelated merges.

## 8. Cleanup

- Merged EDF/PVFS components: retained until retention policy elapses after
  successful publish (see finalization coordinator).
- Do not manually delete component files while `merge_pending` / `merging`.
- Delivery outbox files live beside the watchdog id
  (`{watchdog_id}-sink-delivery.sqlite3`); distinct from telemetry sqlite.

## 9. Rollback

1. Disable creation of new non-CSV sinks in operator policy / UI if needed.
2. Keep deployed binaries that can **read v2 manifests** and stop/recover existing
   multi-sink sessions.
3. Never roll back to a build that only understands CSV-flattened manifests while
   v2 sessions remain recoverable on disk.
4. Owner for rollback decisions: control-plane on-call (record in release notes).

## 10. Observability checklist

- Source/stream: `devices[].stream_status`, watchdog comms.
- Per-sink: health, delivery, buffered/loss counters, failure_kind/message.
- Plot: presentation `dropped` / connected — never rewrite source health.
- Finalization: `acquisition_state`, `artifact_state`, `finalization_id`.

## Quick verification commands

```powershell
# Hermetic sink gates
.\venv\Scripts\python.exe -m pytest -q tests/test_multi_sink_runtime.py tests/test_service_sink_outages.py

# Contract surfaces operators depend on
.\venv\Scripts\python.exe -m pytest -q tests/test_session_config.py tests/test_runtime_manifest.py tests/test_session_status_api.py

# Opt-in hardware (Pod environments only)
$env:RUN_HARDWARE = "1"
.\venv\Scripts\python.exe -m pytest tests/hardware -v
```
