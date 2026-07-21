# System Audit — Pinnacle Control Plane

## Status

Function-implementation audit of the Flask/CLI backend against the command list
in [`backend-control-plane-architecture-plan.md`](./backend-control-plane-architecture-plan.md).

- **Original audit:** 2026-07-02. **Reconciled to gaps-only:** 2026-07-13.
- **Scope:** `app/` (services, API, CLI, runtime host/child, control), `migrations/`, `tests/`
- **This doc now records only open gaps.** The original 2026-07-02
  command-by-command audit, phase table, database write-path table, resolved-
  plan-targets table, and divergences list have been removed — nearly everything
  they flagged is now implemented. For execution status of what remains, defer to
  [`system-audit-implementation.md`](./system-audit-implementation.md). The
  forward-architecture section below is retained: it is the accepted design (the
  "why") for the outstanding runtime_host/watchdog-process split.
- **Migration progress (2026-07-13):** the accepted split is underway — packets
  **02–04 have landed** (runtime/watchdog identity schema; direct-ingest event
  identity with active-watchdog fencing; watchdog SQLite outbox), reviewed and
  green. The "Accepted design" narrative below is now partly realized in code;
  for authoritative per-packet status defer to the M8 table in the roadmap doc.

## Runtime process split: forward architecture (accepted 2026-07-10)

### Accepted target

This audit originally proposed splitting the concrete Morelia `Watchdog`/
`DataFlow` runtime out of `runtime_host` into a second child process. That
proposal is now the **accepted three-process architecture**, tracked as
execution packets 02-12 in
[`docs/migration/README.md`](./migration/README.md):

```text
control plane daemon
  -> HostSupervisor
    -> runtime_host process
      -> watchdog process
          -> Morelia Watchdog / DataFlow stream workers / sinks

watchdog process
  -> local SQLite outbox
  -> direct ingest to control plane
```

Accepted identity model: `session_id` (session/subscription record),
`dataflow_id` (logical acquisition stream), `runtime_id` (runtime host process /
ownership instance), `watchdog_id` (watchdog process instance). `HostSupervisor`
stays a control-plane manager object with no separate durable ID.

This doc uses **watchdog process** — the older "worker"-suffixed name is
retired — because in this codebase "worker" already means a DataFlow
source-to-sink stream worker, and the two terms collided in earlier drafts.

This is lower risk than replacing `runtime_host` outright. The existing daemon
contract stays stable: `HostSupervisor` still spawns `python -m app.runtime_host`,
persists `runtime_port`/`runtime_token`, probes `/status`, and dispatches
commands through the existing loopback command contract. `runtime_host` remains
the command gateway and becomes the watchdog-process supervisor.

### Current boundary

- `HostSupervisor` spawns one `app.runtime_host` process per dataflow and stores
  the runtime port/token plus runtime-ownership row.
- `DataflowRuntimeHost` owns the loopback HTTP API (`/api/v1/commands` and
  `/status`), auth token, lease renewal, report ring, northbound ingest push, and
  lifecycle command threading.
- `LifecycleSafetyGate` owns dataflow/stream command locks and maps command
  envelopes to the `RuntimeControlDriver` interface.
- `MoreliaRuntime` currently implements that driver in-process. It imports
  Morelia lazily, builds pods, `DataFlow`, `ManagedCsvSink`, and the real
  `Watchdog`, calls `flowgraph.collect()`, then runs `watchdog.run()` on a
  background thread.
- `RuntimeReport.sequence` is produced by the driver, and the runtime-host ingest
  path deduplicates on `(dataflow_id, sequence)`. Packet 03 (**done**) added the
  direct-ingest path that dedups on `report_id` and fences on the active
  `watchdog_id`, so a separate watchdog process no longer relies on
  `(dataflow_id, sequence)` alone.

### Accepted design

`WatchdogProcessDriver` replaces the in-process `MoreliaRuntime` and implements
the same `RuntimeControlDriver` protocol. The northbound telemetry path is
**reversed** from the original single-hop proposal:

- `preflight/start/stop/recover/close` are IPC calls from `runtime_host` to the
  watchdog process over an internal host-to-watchdog-process protocol (a local
  HTTP or newline-delimited JSON channel with a per-process token). This is an
  internal boundary, not a new south boundary to the daemon.
- The watchdog process owns all hardware-facing objects: Morelia imports, pod
  instances, serial ports, `DataFlow`, the real `Watchdog`, watchdog threads,
  DataFlow worker processes, and managed sinks.
- **Reversed from the original recommendation:** the watchdog process writes
  each report to a local SQLite outbox first, then sends telemetry **directly**
  to the control plane, instead of relaying everything through `runtime_host`.
  The outbox is the durability boundary if the northbound leg is briefly
  unavailable; `runtime_host` is no longer the sole observable owner of
  northbound events (packet 04: SQLite outbox — **done**; packet 03: event
  identity — **done**).
- Control-plane ingest accepts telemetry **only from the currently active
  `watchdog_id`** for a given `runtime_id` — active-watchdog fencing (packet 07)
  stops a stale or duplicate process from reporting as live.
- A dead or replaced watchdog process is respawned under an explicit claim
  policy (packet 08) so two processes never hold the active claim for the same
  `runtime_id` at once.
- `session stop` must not mark a session completed without **stop proof**
  (packet 09): `runtime_host` must be able to show the watchdog process stopped,
  exited after ack, or emitted a terminal stopped/closed report.

### Engineering breakdown

Tracked as packets 02-12 in [`docs/migration/README.md`](./migration/README.md),
not as a single change. Packets 02 and 03 (identity schema, event identity +
direct ingest) are the highest-risk data-model changes and land before process
supervision work — **both are now done, along with packet 04 (SQLite outbox);
packet 05 (watchdog process entrypoint) is next.** See
`system-audit-implementation.md`'s M8 section for current milestone status.

### Main risks

- **Stop proof:** `session stop` must not mark a session completed until
  `runtime_host` can prove the watchdog process stopped, exited after ack, or
  emitted a terminal stopped/closed report.
- **Event identity and ordering:** `backend_events` idempotency must not depend
  only on `(dataflow_id, sequence)` once the watchdog process ingests directly;
  a stale watchdog process must not be able to keep reporting as active.
- **Failure visibility:** if the watchdog process dies while `runtime_host`
  stays alive, `/status` must surface a clear comms/lifecycle failure instead of
  leaving the last healthy report frozen.
- **Teardown ownership:** the watchdog process must own and close serial ports,
  sinks, DataFlow workers, and the real `Watchdog`; `runtime_host` should only
  supervise the process and report results.
- **Windows subprocess behavior:** manifest paths, `MORELIA_SRC`, tokens, stdout
  handshakes, stderr logs, and signal/terminate handling need explicit tests on
  Windows because this stack is process-heavy already.
- **Protocol drift:** the daemon-facing command contract (north boundary) should
  not change while adding the internal `runtime_host`-to-watchdog-process
  contract.

### Recommendation

Proceed via the packet sequence in `docs/migration/README.md`, after the
hardware lane (0a) and safe-stop guardrail are settled. The split is worth doing
if the goal is fault isolation and diagnosability: a Morelia/Watchdog crash can
become a watchdog-process failure reported by a still-live `runtime_host`,
instead of taking down the same process that owns `/status` and report
buffering.

Do not combine this with monitor/subscriber work or the southbound
runtime-command log unless a packet explicitly says otherwise. Keep the first
migration vertical and narrow: one dataflow, one runtime host, one watchdog
process, existing CLI/API behavior unchanged.

### Acceptance criteria

- Existing daemon-facing API and CLI behavior remain unchanged for
  `session start`, `session watch`, `session status`, `session recover`, and
  `session stop`.
- `runtime_host /status` remains available while the watchdog process is
  running, stopped, or crashed, and includes enough process state to diagnose
  the condition.
- Killing the watchdog process during collection produces an unhealthy/
  unreachable runtime signal without marking the session cleanly completed.
- `backend_events` receive monotonic, non-duplicated identity across watchdog
  process restart attempts for the same dataflow (packet 03).
- Watchdog-process stderr/stdout logs are captured and exposed through the
  existing runtime diagnostic path.
- Hardware verification covers start, recover, clean stop, forced watchdog
  process death, and daemon shutdown with a real `pod8206hr` or `pod8401hr`.

## Remaining gaps (reconciled 2026-07-13)

The 2026-07-02 command-by-command audit, implementation-vs-plan phase table,
database write-path table, resolved-plan-targets table, and divergences list
have been removed: nearly every item they flagged is now implemented — the
device-config 3-tier model (create/edit/delete CLI + routes, claim/release),
guided `session create` + `--template`, host spawn with manifest persist,
`session recover`, incident/gap creation in ingest plus their operator surfaces,
the operations/shutdown CLIs, and the `pod8401hr` schema. What remains open:

| Gap | Roadmap task |
|---|---|
| Runtime host / watchdog-process split — packets 05–12 (05 next) | M8 / migration packets |
| Retire fake-driver tests; establish the hardware lane as the sole gate | 0a |
| Safe-stop completion guardrail — no `completed` without stop proof | Safe-stop guardrail |
| `runtime command list/show` — no `runtime_command` model/route/CLI | 6d |
| Stealable soft device reservations — `claim(force)` + `DeviceClaimConflict` | 4c |
| `device template export --format` still TOML-only | 6b (minor) |
| Monitoring pub/sub fan-out — dormant seam + monitor feature | 7a, 7b (deferred) |
| Registry breadth — models 46/50/52 | 7c (deferred) |
| Output-safe non-`csv` sinks (EDF) | 7d (deferred) |
| Plan Phase 8 — schedules, session duplication, shared dataflows | out of scope |

Full task detail, dependency order, and per-milestone verification live in
[`system-audit-implementation.md`](./system-audit-implementation.md).
