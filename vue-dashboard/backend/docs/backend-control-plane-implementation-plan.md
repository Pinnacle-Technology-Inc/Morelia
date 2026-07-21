# Backend Control Plane — Implementation Plan

## Status

Draft — task-level implementation plan derived from
[`backend-control-plane-architecture-plan.md`](backend-control-plane-architecture-plan.md)
and a full review of the current repo state (including the newly added
`Watchdog/` Morelia source).

**All-sink overlay (2026-07-21):** the CSV vertical slice below remains the
historical spine that unlocked the control plane. Multi-sink support is now
implemented via [`docs/sinks/`](sinks/README.md) (packets 00–30). Do not read
“first sink = CSV” as an active exclusivity claim — see
[`docs/sinks/support-matrix.md`](sinks/support-matrix.md) and
[`docs/sinks/operator-runbook.md`](sinks/operator-runbook.md).

## Date

2026-06-23; all-sink overlay 2026-07-21

## Overview

The architecture plan describes the *target*: a local control plane (Flask +
application services) driving one runtime-agent process per owned dataflow,
which wraps the Morelia Watchdog. This document turns that target into ordered,
verifiable tasks, re-sequenced around what the repo actually contains today.

The spine of this plan is the architecture doc's own recommendation: build **one
production-quality vertical slice** (one device, one safe CSV sink, one session, one
runtime agent, CLI-only, recovery without output overwrite, restart
reconciliation) before broadening. Every stage below either builds toward that
slice or is explicitly deferred until after it is safe.

**Post-slice broadening (done via sinks packets):** EDF/PVFS managed writers +
merge finalization, Influx/Quest delivery outbox, Plot SSE + Vue live view,
multi-sink runtime supervision, and release gates — tracked in
[`docs/sinks/IMPLEMENTATION-STATUS.md`](sinks/IMPLEMENTATION-STATUS.md).

## What the review changed about the plan

These five findings materially re-shape the architecture doc's phasing. They are
the reason this plan is not a 1:1 restatement of Phases 0–8.

1. **Morelia is not installed and is hardware-bound.** `Watchdog/` is reference
   source that imports `Morelia.Devices` / `Morelia.Stream.*` (absent) and whose
   tests need real COM ports. *Consequence:* a **fake runtime/Morelia seam** is a
   first-class, early deliverable — not a footnote inside "add runtime agent."
2. **Output overwrite-on-recovery is inside Morelia.**
   `DataFlowMonitor._rebuild_dataflow` rebuilds sinks from `get_dict()` with the
   same `file_path`, in a mode that can truncate. *Consequence:* output safety
   requires a **managed sink whose reconstruction reopens the same file in append
   mode** (never `w`/truncate) — keeping one continuous file and appending after
   recovery — not just backend metadata. This matches the architecture plan's
   stated preference ("append-only reuse of the same session output path, with a
   new logical segment boundary", `backend-control-plane-architecture-plan.md`).
3. **`Recommend` policy needs a Morelia recovery-decision hook.** Recovery is
   unconditional today. *Decision (confirmed):* `Recommend` is **required in v1**,
   so the Morelia recovery-decision hook (Task 5.3) is **pulled into the first
   slice's critical path**, and `policy` must be threaded session → manifest →
   agent → hook. This adds a Morelia code change to the slice.
4. **Persistence is still in-memory.** `0001_baseline_schema` creates no tables;
   there are no ORM models. *Consequence:* a **persistence foundation** must land
   *with* the service extraction (Phase 1), because services, config revisions,
   operations, and runtime records all depend on it.
5. **The control→agent transport already exists, the agent does not.**
   `app/watchdog/adapters.py` (`HttpWatchdogAdapter`/`FakeWatchdogAdapter`,
   protocol-versioned, localhost-enforced, RFC 9457 error mapping) is solid. The
   *server* side of `docs/watchdog-http-v1.md` — a process that actually answers
   `POST /api/v1/commands` — is greenfield.

## Architecture decisions for this plan

- **SQLite + SQLAlchemy + Alembic stays** the local default (foundation already
  built: WAL pragmas, `transaction()` helper, migration baseline).
- **First device = Pod8206HR, first sink = CSV.** Both are the only types present
  in the Morelia sample tests, so this is forced, not chosen.
- **Reusable configuration (revised 2026-06-30 to three tiers).** *Device
  templates* (reusable per-device parameters — gains, filters, TTL; **mutable**,
  edit-in-place) → *device configs* (NEW: port-bound device instances, key
  `device_type + hardware_id`, built by snapshot-from-template or manual entry) →
  *session configs* (composition: which device configs, each with a sink). Authored
  as TOML, stored as hashed rows in SQLite (the authority). Starting a session
  **snapshots** the resolved config into an immutable runtime manifest the agent
  builds from — the manifest, not the template, is the immutable run record.
  (Original two-tier breakdown in [`stage3-todo/`](stage3-todo/README.md); the
  device-config/template split and ownership/pool are specified in
  [`backend-control-plane-architecture-plan.md`](backend-control-plane-architecture-plan.md)
  *Revised device/ownership model*.)
- **A `RuntimeControlDriver` abstraction** separates the agent from Morelia. `FakeRuntime`
  (no hardware) is the CI default; `MoreliaRuntime` is selected only where the
  full Morelia package + hardware exist. This makes every downstream stage
  testable without hardware.
- **Two CI lanes (confirmed):** the default suite runs `FakeRuntime` and never
  imports Morelia; a separate **hardware-gated job** (pytest marker, e.g.
  `@pytest.mark.hardware`, skipped by default) runs the real `MoreliaRuntime`
  path on a machine with devices attached. Every recovery/output-safety stage
  ships tests in *both* lanes.
- **Output safety is proven against `FakeRuntime` first**, then re-verified
  against real Morelia in the gated job, because the real failure path lives in
  Morelia.
- **Both policies ship in v1 (confirmed):** `Automate` and honest `Recommend`.
  `Recommend` depends on Morelia hook 5.3, which is therefore in the slice.
- **The runtime agent is a separate process** speaking the existing localhost
  HTTP contract — we do not run hardware collection inside Flask request handlers.

## Dependency graph

```
Stage 0  Baseline is green and deterministic           (stabilize tests, single-owner guard)
   │
Stage 1  Sessions persist across restarts              (persistence + application services)
   │            └── typed domain errors, repository, persisted in-flight lock
   │
Stage 2  A dataflow runs in an isolated process        (RuntimeControlDriver + FakeRuntime + host + supervision)
   │
Stage 3  Devices are configured and sessions composed  (discovery + device templates + session composition + manifest)
   │
Stage 4  Recovery never overwrites output  ── RELEASE BLOCKER  (managed append-mode sink + in-file continuity)
   │
Stage 5  Failures recover per the chosen policy        (watchdog hooks; incl. Recommend hook 5.3 — in slice)
   │
Stage 6  Interrupted commands resolve to a known outcome  (durable operations + reconciliation)
   │
Stage 7  Health is observable and replayable           (monitoring + SSE event replay)
   │
Stage 8  The full lifecycle runs from the CLI          (offline subset + state-changing via daemon)
   │
Stage 9  Scheduling, duplication, and broader support  (post-slice)
```

**The first production-quality slice** cuts vertically through Stages 0 → 1 →
3 (discover one 8206HR, save a device template, compose a one-device session with a
CSV sink) → 2 (FakeRuntime agent) → 4 → 5 (incl. lifecycle lock, manifest rebuild,
**and Recommend hook 5.3**) → 6 → 8 (`device list`, session
create/start/watch/stop). Vue controls come *after* the slice is proven safe.

---

## Task list

Sizing: **XS** 1 file · **S** 1–2 · **M** 3–5 · **L** 5–8 (break down if larger).

### Stage 0 — Baseline is green and deterministic
*Technical: Stabilize baseline*

#### Task 0.1: Fix the 4 order-dependent logging-correlation tests

**Description:** `test_request_logging`, `test_sessions::...correlated...`, and two
`test_watchdog_messages` tests pass in isolation but fail in certain run orders.
Root cause: `configure_logging()` mutates *global* logging/structlog state
(`root_logger.handlers.clear()`, `cache_logger_on_first_use=True`) and
`receiver.py` logs via stdlib `logging` while the rest of the app uses
`structlog`, so `caplog` capture of `watchdog_command_received` depends on which
test ran first. Make capture deterministic.

**Acceptance criteria:**
- [ ] `receive_command` logs through the same structlog path as `prepare_command` (consistent capture), or a `conftest` fixture resets logging state per test.
- [ ] All 4 tests pass regardless of order.

**Verification:**
- [ ] `pytest` green, and green again under `pytest -p no:cacheprovider` with a reversed/shuffled order.
- [ ] `ruff check` clean.

**Dependencies:** None
**Files:** `app/watchdog/receiver.py`, `tests/conftest.py`, (maybe) `app/logging_config.py`
**Scope:** S

#### Task 0.2: Commit the in-flight adapter work and document single-owner constraint

**Description:** Land the currently-untracked, already-working pieces
(`app/watchdog/adapters.py`, `tests/test_watchdog_http_contract.py`,
`tests/test_concurrency.py`, the protocol-version changes) as a coherent commit,
and record the operational rule that **only one control-plane daemon may own
hardware at a time**, plus a guard so Flask's debug reloader cannot double-start
hardware-owning code later.

**Acceptance criteria:**
- [ ] Working tree clean after commit; full suite green.
- [ ] README documents the single-owner rule and the `WERKZEUG_RUN_MAIN`/`use_reloader=False` guard for hardware paths.

**Verification:**
- [ ] `pytest` green; `ruff check` clean; `git status` clean.

**Dependencies:** 0.1
**Files:** `README.md`, commit only (no new logic)
**Scope:** XS

#### Checkpoint: Baseline stable
- [ ] All tests pass in any order, lint clean, tree committed. Review before Stage 1.

---

### Stage 1 — Sessions persist across restarts
*Technical: Persistence + application services*

> Replaces `InMemorySessionStore`. Lands persistence *and* the service extraction
> together so services have a real repository (correcting the doc, which defers
> persistence).

#### Task 1.1: Session ORM model + first real migration

**Description:** Define the `Session` SQLAlchemy model (id, name, status, policy,
experiment_id, schedule, device_flows, command_in_flight, command_id,
dataflow_id, watchdog_id, timestamps) on the existing `Base`, and add migration
`0002_sessions` (`down_revision = "0001"`). Replace the dict store with a
SQLite-backed repository using the existing `transaction()` helper.

**Acceptance criteria:**
- [ ] A created session survives across requests/process restart.
- [ ] `alembic upgrade head` then `downgrade base` runs clean on SQLite.
- [ ] `device_flows`/`schedule` round-trip (JSON column) and re-serialize identically through `SessionSchema`.

**Verification:**
- [ ] `pytest -k "session or migration"` green; new repository test green.
- [ ] Manual: create via `POST`, restart app, `GET` still returns it.

**Dependencies:** 0.2
**Files:** `app/models/session.py`, `app/api/store.py`→`app/repositories/sessions.py`, `migrations/versions/0002_sessions.py`, `tests/test_sessions_repository.py`
**Scope:** M

#### Task 1.2: Extract application services + typed domain errors

**Description:** Move business rules out of `app/api/sessions.py` route handlers
into `CreateSession`, `StartSession`, `StopSession`, `GetSessionStatus` services
that raise typed domain errors (`SessionNotFound`, `InvalidTransition`,
`CommandInFlight`, `EmptySession`, `WatchdogUnavailable`…) instead of calling
Flask `abort`/`current_app`. Routes become thin adapters; one mapping layer
turns domain errors into the existing RFC 9457 problem responses.

**Acceptance criteria:**
- [ ] No `abort()`/`current_app` in service modules; routes only parse, call a service, and serialize.
- [ ] Every existing status code (404/409/423/502/503/504) still emitted, via the error map.
- [ ] Services are unit-testable without a Flask request context.

**Verification:**
- [ ] Existing `test_sessions` HTTP behavior unchanged (green).
- [ ] New `tests/test_services_sessions.py` exercises services directly.

**Dependencies:** 1.1
**Files:** `app/services/sessions.py`, `app/services/errors.py`, `app/api/sessions.py`, `app/errors.py` (error map), `tests/test_services_sessions.py`
**Scope:** M

#### Task 1.3: Persist the per-dataflow in-flight lock

**Description:** The "one state-changing command per dataflow" guard is currently
an in-memory dict flag. Move it to a persisted, row-level guard (the
`command_in_flight`/`command_id` columns from 1.1) updated inside `transaction()`,
so the lock survives restarts and concurrent requests.

**Acceptance criteria:**
- [ ] Concurrent `start` on the same session: exactly one wins, the other gets `423 command_in_flight`.
- [ ] Lock state is visible after a process restart.

**Verification:**
- [ ] New concurrency test (two threads, one session) asserts single winner.

**Dependencies:** 1.2
**Files:** `app/services/sessions.py`, `app/repositories/sessions.py`, `tests/test_sessions_locking.py`
**Scope:** S

#### Checkpoint: Persisted, service-driven API
- [ ] Sessions persist; routes are thin; lock is durable. End-to-end create/start/stop flow works against SQLite. Review.

---

### Stage 2 — A dataflow runs in an isolated process
*Technical: Fake runtime seam + runtime-agent skeleton*

> Makes everything downstream testable without Morelia or hardware.

#### Task 2.1: `RuntimeControlDriver` abstraction + `FakeRuntime`

**Description:** Define the interface the agent uses to run one owned dataflow:
`preflight()`, `start()` (build sources/sinks/dataflow + watchdog, `collect`,
`run`), `stop()`, `close()`, and a report callback. Provide `FakeRuntime` (no
hardware) that emits deterministic, scriptable reports modeled on Morelia's
report schema (`watchdog_status`, per-stream `stream_health`, recovery actions).
This is the seam between the agent and `MoreliaRuntime` (added later only where
Morelia + hardware exist).

**Acceptance criteria:**
- [ ] `FakeRuntime` can be driven through preflight → start → (scripted recovery) → stop → close without hardware.
- [ ] Reports match the Morelia combined-report shape the control plane will normalize.

**Verification:**
- [ ] `tests/test_fake_runtime.py` drives the full lifecycle.

**Dependencies:** 0.2 (independent of Stage 1; can start in parallel)
**Files:** `app/runtime_child/driver.py`, `app/runtime_child/fake.py`, `tests/test_fake_runtime.py`
**Scope:** M

#### Task 2.2: Runtime-agent executable serving the localhost command contract

**Description:** Build `Dataflow Runtime Host`: loads an immutable manifest (a dict for now),
constructs a `RuntimeControlDriver`, and serves the **server side** of
`docs/watchdog-http-v1.md` (`POST /api/v1/commands`) plus a status endpoint on
localhost only. Enforces one in-flight lifecycle command per runtime. This is the
real counterpart to `HttpWatchdogAdapter`.

**Acceptance criteria:**
- [ ] `HttpWatchdogAdapter` (real, not Fake) can `start`/`stop` a `FakeRuntime`-backed agent over the loopback socket.
- [ ] A second concurrent lifecycle command is rejected while one is in flight.
- [ ] Binds to loopback only; rejects unknown fields/protocol versions (contract already specifies this).
- [ ] **Auth: loopback-only trust for now** (per decision "decide later"); leave a seam to add a per-agent token before any shared-host/multi-user deployment.

**Verification:**
- [ ] `tests/test_agent_contract.py` runs adapter↔agent over a real localhost port with `FakeRuntime`.

**Dependencies:** 2.1
**Files:** `agent/__main__.py`, `agent/server.py`, `agent/lifecycle.py`, `tests/test_agent_contract.py`
**Scope:** L (split server vs lifecycle if needed)

#### Task 2.3: Control-plane process supervision (spawn / stop / reconnect)

**Description:** Teach the control plane to spawn a `Dataflow Runtime Host` per owned
dataflow, track its pid/port/base-url, stop it, and reconnect to an
already-running agent after a backend restart. Backed by `FakeRuntime` in CI.

**Acceptance criteria:**
- [ ] `StartSession` spawns an agent and dispatches `start` to it; `StopSession` stops it.
- [ ] After a simulated backend restart, the control plane re-attaches to the live agent instead of double-spawning.

**Verification:**
- [ ] `tests/test_agent_supervision.py` covers spawn, stop, and reconnect-after-restart.

**Dependencies:** 2.2, 1.2
**Files:** `app/runtime_child/supervisor.py`, `app/services/sessions.py`, `tests/test_agent_supervision.py`
**Scope:** M

#### Checkpoint: End-to-end with fake hardware
- [ ] CLI-less, but `POST /sessions/{id}/commands/start` spawns an agent, runs a `FakeRuntime`, reports status, and stops cleanly. Review.

---

### Stage 3 — Devices are configured and sessions composed
*Technical: Typed config → immutable revision → runtime manifest*

> **Revised 2026-06-30 — three tiers.** The original Stage 3 used "device config"
> for the reusable parameter set. That is now the **device template** (mutable,
> edit-in-place); a new **device config** is a port-bound device instance (key
> `device_type + hardware_id`) built by snapshotting a template or manual entry.
> A **session** composes device configs (each with a sink). The first session to
> attach a device owns its lifecycle; others attach monitor-only via a live stream
> fan-out; a released device returns to the free pool. A session start still
> **snapshots** the resolved config into an immutable, hashed runtime manifest the
> agent builds from; it never re-reads user TOML. Tasks 3.3/3.4 below predate this
> revision — read them with the rename + new-entity in mind. Authoritative model:
> [`backend-control-plane-architecture-plan.md`](backend-control-plane-architecture-plan.md)
> *Revised device/ownership model*. Packet-level execution: packet 8.0 (rename)
> and the device-config series in [`stage8/`](stage8/README.md).

#### Task 3.1: Device discovery (Device List)

**Description:** Scan connected hardware and report the available devices (port,
hardware id, type), backed by Morelia `pod_scan.detect_pod_devices`. Read-only —
it reports hardware, never owns or configures it. Surfaced later via the CLI
(`ged device list`, Stage 8) and the frontend Device List.

**Acceptance criteria:**
- [ ] Lists attached devices with port / type / hardware id.
- [ ] Absent hardware → empty list, not an error; the scan never opens a long-lived connection.

**Verification:** `tests/test_device_discovery.py` (fake scanner; no hardware in CI).
**Dependencies:** 1.2 · **Files:** `app/services/discovery.py`, `tests/test_device_discovery.py` · **Scope:** S

#### Task 3.2: Typed device registry + parameter schema (8206HR + CSV)

**Description:** Map supported device `type` keys to a validated, **closed
parameter schema** — no arbitrary Python class paths. For `pod8206hr`:
`preamp_gain` (10|100, required) plus writable params (`sample_rate`,
`lowpass_ch0/1/2`, `ttl_pin0..3`), pinned from the Morelia property map, with
string→number coercion. Sink types (`csv`) validated here too (location optional).

**Acceptance criteria:**
- [ ] Unknown device/sink type → typed validation error (not an import).
- [ ] Unknown/typo parameter key → typed error; equal-but-differently-typed inputs canonicalize identically.

**Verification:** `tests/test_registry.py`
**Dependencies:** 1.2 · **Files:** `app/services/registry.py`, `tests/test_registry.py` · **Scope:** S

#### Task 3.3: Reusable device-template store + library management

**Description:** Persist a named, content-hashed **device template** (`{type,
parameters}`) in SQLite. Names are unique (auto-suffix on collision — never a
silent overwrite). Library operations: list, `get_by_name`, **rename / delete
with a `references(name)` warning** (which sessions/configs point at the name),
and TOML/JSON import-export. TOML is import/export only — SQLite is the authority.

> **Revised 2026-06-30:** what this task built is the **device template** library;
> rename `device_config` → `device_template` (packet 8.0). Templates are now
> **mutable** (edit-in-place, not save-as-new) and **`clone` is dropped**. The new
> port-bound **device config** entity is separate work (architecture plan *Revised
> device/ownership model* + stage-8 device-config packets).

**Acceptance criteria:**
- [ ] Same params → same hash; saving over a name auto-suffixes (no overwrite).
- [ ] `rename`/`delete` report the sessions referencing the name; import → export round-trips.

**Verification:** `tests/test_device_templates.py`; migration up/down clean.
**Dependencies:** 3.2 · **Files:** `app/models/device_template.py`, `app/services/device_templates.py`, `migrations/versions/0004_device_templates.py`, `tests/test_device_templates.py` · **Scope:** M

#### Task 3.4: Session composition (many devices, each with a sink)

**Description:** A session binds **one or more** devices; each entry = a chosen
device (hardware id + port from discovery) + a reference to a device template (by
name) + a sink (type + optional location) + an optional nickname (seeded from the
config name, editable). Session-config TOML import/export. The session carries the
recovery `policy` (`automate`/`recommend`).

> **Revised 2026-06-30:** in the three-tier model the session entry references a
> **port-bound device config** (which now carries hardware_id + port + params),
> not a device template by name, and adds attach **role** (responsible vs
> monitor). **Resolved 2026-06-30:** a session *drives* devices via a **dataflow**
> (multiple device sources + sinks, one responsible owner) and may *monitor*
> individual devices extracted from *other* dataflows (per-device mirror,
> dataflow-crossing). The `device_template` reference moves into the device config
> (its snapshot source).

**Acceptance criteria:**
- [ ] A multi-device session imports and round-trips through TOML.
- [ ] A reference to a missing device-template name → typed error; nickname seeds from the template name when absent.

**Verification:** `tests/test_session_config.py`
**Dependencies:** 3.3 · **Files:** `app/services/session_config.py`, `app/models/session.py`, `tests/test_session_config.py` · **Scope:** M

#### Task 3.5: Resolve session → immutable runtime manifest (snapshot at start)

**Description:** At start, resolve a session into an immutable, hashed
`runtime_manifest`: look up each referenced device template **by name**, **snapshot**
its parameters, attach binding + sink + `policy`, then freeze + hash. The agent
builds only from the manifest — never re-reads device-config TOML or the name.
Editing a config later (new name) cannot change a running session; a
renamed/deleted reference **fails loud at resolve, before hardware is touched**.

**Acceptance criteria:**
- [ ] The manifest fully determines the build (device params/sink/dataflow), with no reference back to mutable config; reproducible hash.
- [ ] Manifest carries the session `policy` so the agent + Morelia recovery hook (5.3) honor it.
- [ ] An orphaned reference fails loud and persists nothing; a later config edit leaves a resolved manifest unchanged.

**Verification:** `tests/test_runtime_manifest.py`
**Dependencies:** 3.4, 2.1 · **Files:** `app/models/runtime_manifest.py`, `app/services/manifests.py`, `migrations/versions/0005_runtime_manifest.py`, `tests/test_runtime_manifest.py` · **Scope:** M

#### Checkpoint: Config is authoritative and snapshot-frozen
- [ ] Discover a device → save a reusable device template → compose a session of
  one-or-more devices, each with a sink → a session start resolves a hashed
  manifest that snapshots the configs; the agent runs from the manifest. Review.

---

### Stage 4 — Recovery never overwrites output  (RELEASE BLOCKER)
*Technical: Output safety — one continuous file, append-on-recovery*

> The real overwrite path is `DataFlowMonitor._rebuild_dataflow` rebuilding a
> CSV sink with the same `file_path`. Backend metadata alone cannot stop it.
>
> **Behavior (revised 2026-06-25):** recovery **keeps the existing output file and
> appends to it**, rather than allocating a new physical segment file per recovery.
> The guarantee is unchanged — *a recovery never truncates, overwrites, or deletes
> prior output* — but the mechanism is now append-only reuse of the same path
> (matching the architecture plan's stated preference). Each recovery still records
> a **logical boundary** — now an *offset within the one file*, not a new file.
> The single rule the whole guarantee rides on: the reconstructed sink must reopen
> the existing path in **append mode** (`a` / `O_APPEND`), never `w`, and must not
> re-emit the CSV header. Full work-packet breakdown: [`stage4/`](stage4/README.md).

#### Task 4.1: Managed output file (create-once, reopen-in-append, persisted-before-open)

**Description:** On first start, create the session/sink output file with exclusive
creation (`x` mode / `O_EXCL`) and persist its file metadata **before** the handle
is opened. On every recovery, reopen the **same** path in append mode — never a
truncating mode. Track the append offset (byte/row) so boundaries are recoverable.
Treat a non-writable path, or an unexpected pre-existing path for a *new* session,
as a startup failure (fail closed), not a silent re-create or overwrite.

**Acceptance criteria:**
- [ ] First start creates the file exclusively; a pre-existing path for a new session → startup failure, never reused/overwritten.
- [ ] A recovery reopens the identical path in append mode; prior bytes are preserved and new data lands at EOF.
- [ ] File metadata row (path, owning session/sink, schema hash, current offset) exists before any handle is opened.
- [ ] Non-writable path → startup failure, not silent overwrite.

**Verification:** `tests/test_managed_output_file.py` (append preserves prior bytes; exclusive-create collision; non-writable case)
**Dependencies:** 3.3 · **Files:** `app/output/managed_file.py`, `app/models/output_file.py`, `migrations/versions/0007_output_files.py`, `tests/test_managed_output_file.py` · **Scope:** M

#### Task 4.2: Managed safe CSV sink that reopens in append mode on reconstruction

**Description:** A managed sink wrapper whose **construction** — and whose
`get_dict()` round-trip used by Morelia's `_rebuild_dataflow` — reopens the
**same** file path in append mode with the header suppressed, so even Morelia's
reconstruction-from-snapshot continues the existing file instead of truncating or
deleting it. This is the crux of output safety; prove it against `FakeRuntime`
first, then against Morelia.

**Acceptance criteria:**
- [ ] Reconstructing the sink (simulating `_rebuild_dataflow` with the identical prior config) reopens the *same* file in append mode and continues writing at EOF.
- [ ] An existing output file is never truncated or deleted by a start or a recovery; prior bytes remain byte-for-byte intact.
- [ ] Reconstruction does not re-emit the CSV header (no duplicate header mid-file).
- [ ] `get_dict()` → constructor round-trip is reconstruction-safe (yields append, never truncate).

**Verification:** `tests/test_managed_sink_append_on_recovery.py` (simulate rebuild with identical prior config; assert original bytes intact and new rows appended after them, single header)
**Dependencies:** 4.1 · **Files:** `app/output/managed_csv_sink.py`, `tests/test_managed_sink_append_on_recovery.py` · **Scope:** M

#### Task 4.3: Record gaps and in-file boundaries on recovery

**Description:** On each recovery boundary, persist the gap (last sample before the
failure → first sample after resume) and the **in-file boundary offset** (the
byte/row position in the continuous file where the appended data resumes) so
history stays explicit even though it is one physical file. Reuses the existing
`recovery_gaps` model (`app/models/recovery_gap.py`); `previous_segment_id` /
`next_segment_id` are reinterpreted as the pre-/post-resume offsets within the
file rather than separate-file ids.

**Open sub-decision — partial final row.** If the process died mid-row, the file's
last line may be a truncated CSV record; appending after it yields one malformed
boundary row. Decide one of: (a) accept and mark it in the gap record (simplest),
(b) seek back and overwrite *only the partial trailing record* before appending
(needs proof it never touches a complete prior row), or (c) write a one-line
gap-marker comment row at the boundary. Default to (a) unless a consumer requires
a clean parse.

**Acceptance criteria:**
- [ ] A scripted `FakeRuntime` recovery produces a persisted gap + in-file boundary-offset record.
- [ ] The chosen partial-final-row handling is exercised by a test (failure mid-row → defined, documented outcome).

**Verification:** `tests/test_recovery_boundaries.py`
**Dependencies:** 4.2, 2.3 · **Files:** `app/output/boundaries.py`, `app/models/recovery_gap.py` (reused), `tests/test_recovery_boundaries.py` · **Scope:** M

#### Checkpoint: No-overwrite guarantee proven
- [ ] Recovery against `FakeRuntime` keeps the existing file and appends — never truncates/overwrites/deletes — and records the gap + in-file boundary. **Gate before any real-hardware run.** Review.

---

### Stage 5 — Failures recover per the chosen policy
*Technical: Watchdog hardening hooks (requires Morelia changes)*

> These tasks modify the vendored Morelia `Watchdog/` source. Each needs its own
> Morelia-side test in the **hardware-gated lane** plus a `FakeRuntime` test in CI.
> **All four are in the first slice** — `Recommend` (5.3) is required for v1.

- **Task 5.1 — Per-stream lifecycle lock** covering manual commands *and* automatic
  recovery, exposed as a guarded command facade (`restart`/`reconnect`/`reset`).
  *Acceptance:* a manual command and an auto-recovery cannot run on the same stream
  concurrently. *Files:* `Watchdog/watchdog.py`, `Watchdog/dataflowMonitor.py`,
  Morelia-side test. *Scope:* M
- **Task 5.2 — Manifest-based reconstruction hook** so the agent rebuilds from the
  immutable manifest, not the live `get_dict()` snapshot captured in
  `_capture_dataflow_info`. *Scope:* M
- **Task 5.3 — Recovery-decision hook (honest `Recommend`) — IN SLICE.** Add a
  decision point in `StreamWatcher`'s escalation path: under `Automate` it recovers
  as today; under `Recommend` it stops/reports and **waits for an explicit command**
  from the control plane instead of auto-rebuilding. Policy arrives via the manifest
  (3.3). *Acceptance:* in `Recommend`, a forced failure produces a "needs action"
  report and **no** rebuild until a guarded command (5.1) is issued; in `Automate`,
  it rebuilds automatically. *Files:* `Watchdog/watchdog.py`, agent wiring,
  Morelia-side + `FakeRuntime` tests. *Scope:* M
- **Task 5.4 — Structured recovery events** emitted from `on_result` /
  `on_stream_result` callbacks, normalized for the control plane to persist. *Scope:* S

**Dependencies:** 4.2 (managed sink before reconstruction is exercised), 3.3 (policy in manifest, for 5.3)
**Checkpoint:** Manual + auto recovery are mutually exclusive; rebuild uses manifest; **`Recommend` waits for an explicit command while `Automate` self-heals**; events flow. Review.

---

### Stage 6 — Interrupted commands resolve to a known outcome
*Technical: Durable operations + reconciliation*

- **Task 6.1 — Operations table + request keys + state machine**
  (`queued→claimed→dispatched→running→verifying→succeeded|failed|uncertain`);
  one active op per dataflow. *Scope:* M
- **Task 6.2 — Runtime/process ownership records** (pid, port, manifest hash, owner). *Scope:* S
- **Task 6.3 — Startup reconciliation**: on backend restart, decide each in-flight
  op's true outcome; surface `uncertain` for explicit operator resolution before
  the next risky command. *Scope:* M

**Dependencies:** 2.3, 1.3
**Checkpoint:** Kill the backend mid-`start`; on restart the op resolves to succeeded/failed/uncertain and blocks risky commands while uncertain. Review.

---

### Stage 7 — Health is observable and replayable
*Technical: Monitoring + event replay*

- Normalize runtime reports into persisted backend events; **stamp backend-side
  UTC** (Morelia times are process-relative — confirmed: `_now_rel()` /
  `_PROGRAM_START`). Add SSE event IDs + replay; distinguish healthy / delayed /
  unreachable / stopped / recovering / failed / unknown. *Scope:* M–L

**Dependencies:** 5.4, 6.1

---

### Stage 8 — The full lifecycle runs from the CLI
*Technical: CLI surface*

- Thin `ged` CLI: argument parsing + formatting only. **Offline** subset
  (`device template validate|diff|export`, `doctor`, manifest inspect) runs without
  the daemon; **state-changing** commands (`device list` (discovery + pool
  status), `device template import|edit|rename|delete`, `device template`
  (create interactive / `--template`), `device edit|delete`,
  `session create|start|watch|stop`, `operation show`, `runtime list|reconcile`)
  go through the daemon API. (Revised 2026-06-30: `device template` → `device
  template` for the library; new port-bound `device template`/`device edit`; no
  `clone`.) *Scope:* M

**Dependencies:** 1.2 (services), 3.2 (offline config), 6.1 (operations)
**Checkpoint — FIRST PRODUCTION-QUALITY SLICE COMPLETE:** `ged device list`
discovers a device, `ged device template` saves a reusable config, and `ged session
create/start/watch/stop` composes and drives a session (one 8206HR + one managed
CSV sink) via one agent — recovering without overwrite, resolving a known outcome
after restart, and honoring **both `Automate` (self-heal) and `Recommend`
(report-and-wait) policies** — all on `FakeRuntime` in CI, and on real Morelia in
the hardware-gated job. Review before adding Vue.

---

### Stage 9 — Scheduling, duplication, and broader support
*Technical: Post-slice (deferred)*

Schedules (manual/daily), session duplication from immutable snapshots, shared
dataflow ownership + safe detach, Vue controls (Device List + Template List +
session builder UIs), broader device/sink support (e.g. `pod8401hr`), honest
`Recommend` (Task 5.3) if not already landed.

> **Revised 2026-06-30 — device pool, ownership & monitoring fan-out.** Shared
> dataflow ownership concretizes as: a device config is driven within one
> **dataflow** (multiple devices + sinks) owned by the **responsible** session;
> other sessions **monitor individual devices extracted from *other* dataflows**
> (per-device mirror into their own sink, no control, dataflow-crossing); release
> returns the device to the **free pool** (`device list` status `free`/`claimed`).
> The **per-device** publish-subscribe stream shape this needs should be designed
> into the runtime earlier (Stages 2/4) even if monitors ship here — retrofitting a
> per-device 1→N tee later is a runtime rewrite. Route the claim through the
> existing runtime-ownership records (Stage 6), not a new lock.

---

## Risks and mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Morelia not importable / hardware-bound; can't test in CI | High | `RuntimeControlDriver` + `FakeRuntime` seam (2.1) is CI default; real `MoreliaRuntime` runs in the hardware-gated job |
| Output overwrite on recovery (inside Morelia) | **Release blocker** | Managed sink reopens the same file in append mode on reconstruction (4.2) — never `w`/truncate — over a create-once managed file (4.1); gate Stage 4 checkpoint; re-verify in gated job. **Larger blast radius than fresh-segment** (one bad `w` truncates the whole recording): defend the append-only rule with the reconstruction round-trip test and the partial-final-row test (4.3). |
| `Recommend` required in v1 but Morelia auto-recovers unconditionally | High | Recovery-decision hook (5.3) is in the slice; policy flows via manifest (3.3); test both policies in CI (`FakeRuntime`) and the gated job |
| Morelia hook 5.3 on the critical path delays the slice | Medium | Keep the hook additive/minimal (one decision point in escalation); land 5.1 lock first so report-and-wait is safe |
| Global logging state leaks between tests | Medium | Fix capture path / per-test reset (0.1); run suite shuffled |
| Modifying vendored Morelia introduces regressions | Medium | Each Stage-5 hook gets a Morelia-side test; keep hooks additive |
| Process-relative watchdog timestamps misread as wall-clock | Medium | Backend stamps UTC on ingest (Stage 7) |
| Concurrency on the per-dataflow lock | Medium | Persisted row-level lock (1.3) + concurrency test |

## Decisions (resolved 2026-06-23)

1. **Runtime strategy for Morelia** — ✅ **Both**: `FakeRuntime` is the CI default
   (never imports Morelia); a separate **hardware-gated job** runs real
   `MoreliaRuntime` on a machine with devices. Recovery/output stages ship tests
   in both lanes.
2. **`Recommend` in first release?** — ✅ **Required in v1.** Morelia
   recovery-decision hook (5.3) is in the first slice; `policy` flows
   session → manifest → agent → hook.
3. **Agent ↔ control-plane auth on localhost** — ✅ **Decide later.** Task 2.2 is
   loopback-only trust with a seam for a per-agent token before any
   shared-host/multi-user deployment.

## Open decisions (still need confirmation)

- **First device/sink** — ✅ **confirmed Pod8206HR + CSV** (the only types in the
  Morelia samples; the two-tier config model is built around them first).
- **Device-config / session-config TOML formats** — control-plane-owned, authored
  via CLI/frontend, import/export only (SQLite is the authority). Device-config
  TOML stays shape-compatible with Morelia device files (parameter tables, and a
  `type` inferable from a `title` like `"Pod8206HR Device Configuration File"`) so
  existing files import. Session-config TOML replaces Morelia's experiment manifest
  and adds per-device sink assignment.
- **Legacy Morelia experiment-manifest ingestion** (`test3.toml` shape) — decide in
  Task 3.4 whether to provide an adapter or accept only the new session format.
- **CLI package/executable name** — assumed `ged` / `Dataflow Runtime Host`.
- **(2026-06-30, RESOLVED) Session↔device binding** — a session **drives** devices
  via a **dataflow** (multiple device sources + sinks, one responsible owner / one
  agent) and may **monitor** individual devices extracted from *other* dataflows
  (per-device mirror, dataflow-crossing). Fan-out is per-device-report; a monitor
  session can aggregate device-mirrors from several dataflows. (Was "Session→
  device-config edge".)
- **(2026-06-30) Device-config edit-sever** — hard vs soft (provenance-retaining)
  when an edit declines to update the source template. Leaning soft.
- **(2026-06-30) `hardware_id` format** — opaque string until confirmed on real
  hardware; revisit the `device_type + hardware_id` key once known.

## Non-goals (unchanged from architecture plan)

Replacing Morelia Watchdog; rebuilding the Vue UI; supporting every device
immediately; treating raw TOML as live runtime state; allowing multiple
independent processes to control the same physical device.
