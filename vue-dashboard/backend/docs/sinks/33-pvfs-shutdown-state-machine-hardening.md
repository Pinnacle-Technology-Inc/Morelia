# Packet 33 — Harden PVFS shutdown with acknowledged phases

Status: ready for implementation  
Approved: 2026-07-29  
Depends on: Packet 32 Unit 0 decision record  
Blocks: Packet 32 spawned-process artifact gate and hardware release gate

## Outcome

Replace inferred shutdown success with an explicit parent-owned state machine.
The DataFlow worker acknowledges every required teardown phase; a managed PVFS
writer subprocess acknowledges drain, native flush, native close, and artifact
verification. The parent prints one bounded, correlated line for every action.

This packet prevents recurrence. It does not repair or delete existing PVFS or
`temp_*.db3` files.

## Confirmed policy

- Forced termination makes the entire stop operation fail.
- A worker exit code of zero is necessary but not sufficient for success.
- A PVFS component is `clean/complete` only after close and embedded-catalog
  verification are acknowledged.
- Missing, late, out-of-order, or failed required acknowledgements fail the
  stop. They are never inferred from process death.
- Unverified PVFS components are quarantined and excluded from automatic merge.
- Existing malformed artifacts remain byte-for-byte unchanged; salvage is a
  separate task.

## Evidence and gap disposition

Observed:

- `DataFlowMonitor._stop_stream_unlocked()` terminates a live worker after its
  join timeout and currently returns `ok=True`.
- `get_data_wrapper()` currently converts any `BaseException` raised after the
  stop event into exit code 0.
- `DataFlow.stop_collection()` has the same join/terminate shape but returns no
  result or phase evidence.
- `ManagedPvfsSink._pvfs_writer_target()` can return silently on create/channel
  failure. `_stop_writer_process()` observes only liveness and does not require
  drain/flush/close acknowledgements.
- Runtime logging has one aggregate `dataflow_shutdown_completed` event plus
  unrelated ad-hoc `print()` calls. It cannot identify a missing shutdown phase.

Inferred:

- A process exit alone cannot prove that the source released the port, every
  sink context exited, or the embedded PVFS catalog was verified.

Unknown:

- Which process created the second group of empty DB3 files seen on July 21.
  This packet makes future actor/PID/action evidence durable but does not assign
  a cause retroactively.

Gap disposition: Packet 32 gaps PVFS-02, PVFS-03, and PVFS-09 through PVFS-11
are owned by Units 1–6 below. Packet 32 Unit 4 remains the artifact-level gate.

## Protocol contract

### Required top-level state sequence

The monitor owns the state machine. One state machine exists per stream and per
stop attempt, identified by a new UUID `shutdown_id`.

```text
requested                         (parent action)
  -> stop_observed                (worker acknowledgement)
  -> source_stopped               (worker acknowledgement)
  -> sinks_finalizing             (worker acknowledgement)
  -> sinks_finalized              (worker acknowledgement)
  -> worker_exiting               (worker acknowledgement)
  -> worker_exited                (parent observation; exit code must be 0)
  -> complete                     (parent terminal state)
```

From any non-terminal state:

```text
phase_failed | protocol_violation | deadline_expired
  -> force_termination_requested  (only if worker is still alive)
  -> forced_termination           (parent observation)
  -> failed                       (parent terminal state)
```

`failed` is also terminal when the worker has already exited. A duplicate of
the current acknowledgement is idempotent and remains visible in the transcript.
A skipped or regressing required phase is a `protocol_violation`.

One absolute monotonic deadline applies to the complete stream shutdown. A
phase acknowledgement never extends that deadline.

### Managed PVFS writer evidence

When `ManagedPvfsSink.use_writer_process` is true, these writer-child actions
must occur before the DataFlow worker may acknowledge `sinks_finalized`:

```text
writer_stop_observed
writer_queue_drained
writer_native_flushed
writer_native_closed
pvfs_catalog_verified
```

The last action is emitted by the DataFlow worker after independent read-only
catalog verification. Missing writer evidence, a non-zero writer exit, writer
force termination, native close returning false, or verification failure makes
sink close raise and makes the top-level shutdown fail.

For in-process managed PVFS, `writer_*` actions do not apply, but
`pvfs_catalog_verified` remains required before `sinks_finalized`.

### Stable shutdown-action schema

Every action is a plain, picklable record. Version 1 has these fields:

| Field | Required | Contract |
|---|---|---|
| `schema_version` | yes | Integer `1`. |
| `shutdown_id` | yes | UUID string created by the parent for one stream stop attempt. |
| `stream_index` | yes | Non-negative integer; bounded cardinality. |
| `actor` | yes | `runtime`, `monitor`, `dataflow_worker`, `sink`, or `pvfs_writer`. |
| `actor_pid` | yes | Integer PID, or `null` before a process exists. |
| `phase` | yes | One state-machine phase from this packet. |
| `action` | yes | Stable snake-case action name. |
| `outcome` | yes | `started`, `acknowledged`, `completed`, `failed`, `timed_out`, `forced`, or `duplicate`. |
| `emitted_at_ns` | yes | Wall-clock nanoseconds for correlation; not used for deadlines. |
| `sink_id` | no | Bounded stable sink identity when actor is a sink/writer. |
| `output_id` | no | Bounded stable output identity when known. |
| `worker_exitcode` | no | Integer parent observation. |
| `error_type` | no | Exception class name, maximum 120 characters. |
| `reason` | no | Redacted diagnostic, maximum 500 characters. |

The parent adds `action_seq` in queue-consumption order and `elapsed_ms` from its
monotonic start. Worker-provided sequence numbers are not trusted across nested
processes. Do not log packet contents, credentials, full manifests, native
handles, or unbounded filesystem paths.

### Required operator printout

The runtime emits one structured log event named `dataflow_shutdown_action` for
every transcript record, followed by one `dataflow_shutdown_summary`. In the
configured console renderer, a successful writer-process shutdown must be
readable in this form (identifiers are examples):

```text
dataflow_shutdown_action shutdown_id=4f3... action_seq=1 stream_index=0 actor=monitor actor_pid=4100 phase=requested action=stop_requested outcome=started elapsed_ms=0
dataflow_shutdown_action shutdown_id=4f3... action_seq=2 stream_index=0 actor=dataflow_worker actor_pid=8920 phase=stop_observed action=stop_event_observed outcome=acknowledged elapsed_ms=7
dataflow_shutdown_action shutdown_id=4f3... action_seq=3 stream_index=0 actor=dataflow_worker actor_pid=8920 phase=source_stopped action=source_port_closed outcome=acknowledged elapsed_ms=31
dataflow_shutdown_action shutdown_id=4f3... action_seq=4 stream_index=0 actor=dataflow_worker actor_pid=8920 phase=sinks_finalizing action=sink_close_started outcome=acknowledged sink_id=pvfs-main elapsed_ms=33
dataflow_shutdown_action shutdown_id=4f3... action_seq=5 stream_index=0 actor=pvfs_writer actor_pid=9012 phase=sinks_finalizing action=writer_stop_observed outcome=acknowledged sink_id=pvfs-main elapsed_ms=35
dataflow_shutdown_action shutdown_id=4f3... action_seq=6 stream_index=0 actor=pvfs_writer actor_pid=9012 phase=sinks_finalizing action=writer_queue_drained outcome=completed sink_id=pvfs-main elapsed_ms=49
dataflow_shutdown_action shutdown_id=4f3... action_seq=7 stream_index=0 actor=pvfs_writer actor_pid=9012 phase=sinks_finalizing action=writer_native_flushed outcome=completed sink_id=pvfs-main elapsed_ms=65
dataflow_shutdown_action shutdown_id=4f3... action_seq=8 stream_index=0 actor=pvfs_writer actor_pid=9012 phase=sinks_finalizing action=writer_native_closed outcome=completed sink_id=pvfs-main elapsed_ms=71
dataflow_shutdown_action shutdown_id=4f3... action_seq=9 stream_index=0 actor=sink actor_pid=8920 phase=sinks_finalizing action=pvfs_catalog_verified outcome=completed sink_id=pvfs-main output_id=out-123 elapsed_ms=80
dataflow_shutdown_action shutdown_id=4f3... action_seq=10 stream_index=0 actor=dataflow_worker actor_pid=8920 phase=sinks_finalized action=all_sinks_closed outcome=acknowledged elapsed_ms=82
dataflow_shutdown_action shutdown_id=4f3... action_seq=11 stream_index=0 actor=dataflow_worker actor_pid=8920 phase=worker_exiting action=worker_exit_started outcome=acknowledged elapsed_ms=83
dataflow_shutdown_action shutdown_id=4f3... action_seq=12 stream_index=0 actor=monitor actor_pid=4100 phase=worker_exited action=worker_exit_observed outcome=completed worker_exitcode=0 elapsed_ms=101
dataflow_shutdown_action shutdown_id=4f3... action_seq=13 stream_index=0 actor=monitor actor_pid=4100 phase=complete action=shutdown_completed outcome=completed elapsed_ms=102
dataflow_shutdown_summary shutdown_id=4f3... stream_index=0 terminal_phase=complete ok=true forced_termination=false worker_exitcode=0 action_count=13 missing_phases=[] elapsed_ms=102
```

Failure output must show the last acknowledged phase, the timeout/failure
action, forced-termination actions if applicable, and `ok=false`. Tests assert
structured fields, never the renderer's whitespace.

Example when the worker acknowledges source shutdown but stalls before sinks
finish:

```text
dataflow_shutdown_action shutdown_id=9ac... action_seq=1 stream_index=0 actor=monitor actor_pid=4100 phase=requested action=stop_requested outcome=started elapsed_ms=0
dataflow_shutdown_action shutdown_id=9ac... action_seq=2 stream_index=0 actor=dataflow_worker actor_pid=8920 phase=stop_observed action=stop_event_observed outcome=acknowledged elapsed_ms=6
dataflow_shutdown_action shutdown_id=9ac... action_seq=3 stream_index=0 actor=dataflow_worker actor_pid=8920 phase=source_stopped action=source_port_closed outcome=acknowledged elapsed_ms=29
dataflow_shutdown_action shutdown_id=9ac... action_seq=4 stream_index=0 actor=dataflow_worker actor_pid=8920 phase=sinks_finalizing action=sink_close_started outcome=acknowledged sink_id=pvfs-main elapsed_ms=31
dataflow_shutdown_action shutdown_id=9ac... action_seq=5 stream_index=0 actor=monitor actor_pid=4100 phase=deadline_expired action=phase_deadline_expired outcome=timed_out reason=missing:sinks_finalized,worker_exiting elapsed_ms=15000
dataflow_shutdown_action shutdown_id=9ac... action_seq=6 stream_index=0 actor=monitor actor_pid=4100 phase=force_termination_requested action=worker_terminate_requested outcome=started elapsed_ms=15001
dataflow_shutdown_action shutdown_id=9ac... action_seq=7 stream_index=0 actor=monitor actor_pid=4100 phase=forced_termination action=worker_terminated outcome=forced worker_exitcode=-15 elapsed_ms=15019
dataflow_shutdown_action shutdown_id=9ac... action_seq=8 stream_index=0 actor=monitor actor_pid=4100 phase=failed action=shutdown_failed outcome=failed reason=required_acknowledgement_timeout elapsed_ms=15020
dataflow_shutdown_summary shutdown_id=9ac... stream_index=0 terminal_phase=failed ok=false forced_termination=true worker_exitcode=-15 action_count=8 missing_phases=[sinks_finalized,worker_exiting] elapsed_ms=15020
```

## Compatibility and safety boundaries

- New callback/queue parameters are optional and default to `None`; existing
  non-watchdog callers remain source compatible.
- Queue consumers use blocking `get(timeout=...)`/`get_nowait()`, never
  `Queue.empty()` as a correctness check.
- Transcript storage is bounded to 256 actions per stream. Exceeding the bound
  emits one `transcript_overflow` failure and fails the stop.
- Queue/callback reporting failures during shutdown fail the protocol; they are
  not swallowed as acquisition-only telemetry failures.
- Stop locks retain their existing acquisition order. No queue wait occurs
  while holding a lock needed by the worker.
- No unit touches the July 21 artifacts or installed `site-packages`.

## Execution order

Execute Units 1–6 serially. A smaller model must stop at the first failed unit
and use that unit's failure handling; it must not weaken the protocol to make a
later test pass.

---

## Unit 1: Define the shutdown protocol reducer

Status: ready  
Size: S  
Depends on: Packet 32 Unit 0

### Exact read set

- `src/Morelia/Stream/data_flow.py` — current process slots and stop deadline.
- `src/Morelia/Stream/source.py` — worker entrypoint and teardown order.
- `src/Morelia/Watchdog/dataflowMonitor.py` — parent stop owner.
- `vue-dashboard/backend/docs/sinks/33-pvfs-shutdown-state-machine-hardening.md`
  — normative protocol above.

Do not search unless a listed path is absent. Search budget: one query,
`ShutdownPhase`.

### Exact edit set

- `src/Morelia/Stream/shutdown.py` (new)
- `tests/test_shutdown_protocol.py` (new)

### Contract / invariant

Implement immutable action records, vocabulary constants/enums, a bounded
transcript, and a pure reducer. The reducer has no multiprocessing, sleeping,
logging, filesystem, or backend imports.

### Acceptance criteria

- [ ] The happy sequence reaches `complete` only after every required phase and
  exit code 0.
- [ ] Skipped/regressing phases, non-zero exit, timeout, forced termination, and
  transcript overflow reach `failed` with stable reason codes.
- [ ] Duplicate current-phase acknowledgements are idempotent and visible.

### Verification

From `C:/Users/ahoang/Morelia` run:

```powershell
& 'C:\Users\ahoang\vue-dashboard\backend\venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider tests\test_shutdown_protocol.py
```

Expected: all protocol tests pass.

### Failure handling

If any transition is ambiguous, update this document and stop. Do not encode a
new transition from test intuition.

### Handoff

Report exported symbols, transition table, reason codes, and exact test result.

---

## Unit 2: Emit DataFlow worker acknowledgements

Status: ready after Unit 1  
Size: M  
Depends on: Unit 1

### Exact read set

- `src/Morelia/Stream/shutdown.py` — Unit 1 contract.
- `src/Morelia/Stream/source.py` — `_stream_from_pod_device`, `get_data`,
  `get_data_wrapper`, `_bind_sink_error_callbacks`.
- `src/Morelia/Stream/data_flow.py` — `DataFlow._start_collecting`,
  `stop_collection`.
- `tests/test_sink_error_reporting.py` — current wrapper/error fixtures.

Search budget: two queries, only `get_data_wrapper(` and `_manual_stop_events`.

### Exact edit set

- `src/Morelia/Stream/source.py`
- `src/Morelia/Stream/data_flow.py`
- `tests/test_shutdown_worker.py` (new)

### Contract / invariant

Create one parent-owned status queue and `shutdown_id` slot per stream. Pass a
picklable reporter into the worker. Emit required acknowledgements at the actual
boundaries: after observing stop, after source context/port close, immediately
before sink contexts exit, after all sink contexts return, and immediately
before successful worker return. A close exception emits `phase_failed` and
remains a non-zero worker exit; remove the broad shutdown `BaseException -> 0`
conversion. Preserve the explicitly bounded quiet behavior for shutdown-only
`KeyboardInterrupt`, `OSError`, and `BrokenPipeError` only before sink
finalization begins.

### Acceptance criteria

- [ ] A simulated clean worker emits every required acknowledgement in order.
- [ ] Source-close and sink-close failures emit the failing phase and produce a
  non-zero exit path; no `sinks_finalized` follows failure.
- [ ] Existing callers without a reporter still work, and existing sink-write
  isolation tests remain green.

### Verification

```powershell
& 'C:\Users\ahoang\vue-dashboard\backend\venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider tests\test_shutdown_worker.py tests\test_sink_error_reporting.py
```

### Failure handling

Do not add sleeps to make phase order pass. If Rx completion prevents an exact
boundary acknowledgement, capture the actual call order and stop for packet
revision.

### Handoff

Report worker argument compatibility, exact emission sites, exception policy,
and test count.

---

## Unit 3: Enforce acknowledgements in DataFlowMonitor

Status: ready after Unit 2  
Size: M  
Depends on: Unit 2

### Exact read set

- `src/Morelia/Stream/shutdown.py` — reducer and transcript.
- `src/Morelia/Stream/data_flow.py` — status-queue/shutdown-ID slots.
- `src/Morelia/Watchdog/dataflowMonitor.py` — `attach`, `_make_worker`,
  `_stop_stream_unlocked`, `_stop_dataflow_reserved`, restart paths.
- `tests/test_watchdog_lifecycle.py` — fake processes and lifecycle assertions.

Search budget: two queries, only `_make_worker(` and `_stop_stream_unlocked(`.

### Exact edit set

- `src/Morelia/Watchdog/dataflowMonitor.py`
- `src/Morelia/Stream/data_flow.py`
- `tests/test_watchdog_lifecycle.py`

### Contract / invariant

Both public `DataFlow.stop_collection()` and watchdog stop use the same reducer
and absolute-deadline coordinator. The coordinator consumes actions while the
worker exits, drains actions already queued after exit, then evaluates required
phases and exit code. Restarted workers receive fresh queue/ID slots. Whole-flow
stop attempts every stream and fails if any stream is not `complete`.

### Acceptance criteria

- [ ] Clean exit with all acknowledgements returns `ok=True` plus the bounded
  transcript; missing/out-of-order acknowledgement or non-zero exit is failure.
- [ ] A live worker at deadline is terminated, recorded as forced, and returns
  `ok=False`; a missing worker slot is idempotent only when already stopped.
- [ ] Whole-flow stop attempts all streams and retains each stream transcript,
  including failures.

### Verification

```powershell
& 'C:\Users\ahoang\vue-dashboard\backend\venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider tests\test_shutdown_protocol.py tests\test_shutdown_worker.py tests\test_watchdog_lifecycle.py
```

### Failure handling

If queue waiting deadlocks, record held locks and worker stack evidence and
stop. Do not increase the timeout or bypass an acknowledgement.

### Handoff

Report result schema, deadline behavior, forced-termination evidence, and tests.

---

## Unit 4: Require managed PVFS writer evidence

Status: ready after Unit 3  
Size: M  
Depends on: Unit 3

### Exact read set

- `src/Morelia/Stream/source.py` — sink reporter binding and tracked sink exit.
- `src/Morelia/Stream/shutdown.py` — action schema.
- `vue-dashboard/backend/app/output/managed_pvfs_sink.py` —
  `_pvfs_writer_target`, `_start_writer_process`, `_stop_writer_process`,
  `_finalize_segment`, `_verify_finalized_container`.
- `vue-dashboard/backend/tests/test_managed_pvfs_sink.py` — direct close and
  writer-process tests.
- `vue-dashboard/backend/tests/test_sink_worker_ownership.py` — reconstructed
  worker ownership fixture.

Search budget: one query, `bind_shutdown`.

### Exact edit set

- `src/Morelia/Stream/source.py`
- `vue-dashboard/backend/app/output/managed_pvfs_sink.py`
- `vue-dashboard/backend/tests/test_managed_pvfs_sink.py`

### Contract / invariant

Bind an optional shutdown reporter after worker reconstruction, just like the
sink-error reporter. The nested writer reports stop/drain/flush/close actions.
The owning sink requires those actions plus writer exit code 0, then verifies
the embedded catalog and emits `pvfs_catalog_verified`. Any missing action,
force termination, non-zero exit, native false return, or verification error
raises `ManagedPvfsSinkError`; the output remains interrupted/quarantined.

### Acceptance criteria

- [ ] Clean in-process and writer-process finalization emit their applicable
  actions and only then return from sink close.
- [ ] Each injected create/drain/flush/close/exit/verification failure is visible
  and prevents `clean/complete` plus top-level `sinks_finalized`.
- [ ] Writer processes and queues are joined/closed with no orphan or locked
  pytest path.

### Verification

From `C:/Users/ahoang/Morelia/vue-dashboard/backend` run:

```powershell
& 'C:\Users\ahoang\vue-dashboard\backend\venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider tests\test_managed_pvfs_sink.py tests\test_sink_worker_ownership.py
```

### Failure handling

Keep pytest-owned artifacts and record PID, exit code, last action, and locked
path on failure. Do not patch installed pypvfs or hide handle failures with
retries.

### Handoff

Report action order for both modes, injected failures, durable output state,
child cleanup, and tests.

---

## Unit 5: Print and propagate the shutdown transcript

Status: ready after Unit 4  
Size: S  
Depends on: Unit 4

### Exact read set

- `vue-dashboard/backend/app/runtime_child/morelia.py` —
  `MoreliaRuntime.stop`, `close`, current shutdown logs.
- `vue-dashboard/backend/app/runtime_child/driver.py` — runtime stop interface.
- `vue-dashboard/backend/tests/test_runtime_multi_sink_stack.py` — current stop
  ordering and dirty-worktree context.
- `src/Morelia/Watchdog/dataflowMonitor.py` — Unit 3 result schema.
- `vue-dashboard/backend/docs/sinks/33-pvfs-shutdown-state-machine-hardening.md`
  — required printout schema.

Search budget: one query, `dataflow_shutdown_completed`.

### Exact edit set

- `vue-dashboard/backend/app/runtime_child/morelia.py`
- `vue-dashboard/backend/tests/test_runtime_shutdown_integrity.py` (new)

Before editing, inspect and preserve the existing user diff in
`morelia.py`; do not reformat or overwrite unrelated recovery work.

### Contract / invariant

For every returned action, emit one `dataflow_shutdown_action` with the stable
fields above, in `action_seq` order, then one summary. `ok=False`, a missing
complete transcript, or forced termination raises an actionable runtime error,
does not emit a stopped-success report, and does not transition to `STOPPED`.
Watchdog cleanup still runs once.

### Acceptance criteria

- [ ] Captured structured logs contain every action exactly once in order and a
  summary with terminal phase/action count/missing phases.
- [ ] Forced, timed-out, protocol-invalid, and non-zero exits raise and never
  emit a stopped-success report.
- [ ] A complete transcript still closes the watchdog and transitions to
  `RuntimePhase.STOPPED`.

### Verification

From `C:/Users/ahoang/Morelia/vue-dashboard/backend` run:

```powershell
& 'C:\Users\ahoang\vue-dashboard\backend\venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider tests\test_runtime_shutdown_integrity.py tests\test_runtime_multi_sink_stack.py
```

### Failure handling

If the existing dirty diff overlaps the exact stop/logging lines, stop and hand
off the diff hunk; do not discard or rewrite user work.

### Handoff

Paste one successful and one forced-termination structured transcript, then
report phase/report behavior and tests.

---

## Unit 6: Prove the spawned shutdown boundary

Status: ready after Unit 5  
Size: M  
Depends on: Unit 5

### Exact read set

- `src/Morelia/Stream/shutdown.py` — final protocol.
- `src/Morelia/Stream/data_flow.py` — real process construction/stop.
- `src/Morelia/Stream/source.py` — worker reconstruction/close.
- `src/Morelia/Watchdog/dataflowMonitor.py` — parent coordinator.
- `vue-dashboard/backend/app/output/managed_pvfs_sink.py` — actual sink.
- `vue-dashboard/backend/tests/test_managed_pvfs_sink.py` — pypvfs readers and
  exact-value helpers.
- `vue-dashboard/backend/docs/sinks/32-pvfs-finalization-integrity.md` — final
  artifact gate.

Search budget: two queries, `multiprocessing.get_context` and `PvfsFile.extract`.

### Exact edit set

- `vue-dashboard/backend/tests/test_pvfs_shutdown_state_machine.py` (new)
- `vue-dashboard/backend/docs/sinks/33-pvfs-shutdown-state-machine-hardening.md`
  — append closeout results only.

### Contract / invariant

Use Windows-compatible `spawn`, simulated source data, real managed PVFS, and a
pytest-owned unique path. This unit proves the acknowledgement protocol across
the real process topology. Packet 32 Unit 4 owns exhaustive independent
channel/sample/hash/residue validation. Join/close every process and queue.
Never touch production output.

### Acceptance criteria

- [ ] Clean shutdown produces the full acknowledgement transcript, exit code 0,
  and a `pvfs_catalog_verified` action before `sinks_finalized`.
- [ ] A deliberately stalled worker and a deliberately failed PVFS close each
  produce a complete failure transcript and never report clean completion.
- [ ] Teardown leaves no child process or locked pytest path; exhaustive
  byte/sample/residue proof remains assigned to Packet 32 Unit 4.

### Verification

From `C:/Users/ahoang/Morelia/vue-dashboard/backend` run:

```powershell
& 'C:\Users\ahoang\vue-dashboard\backend\venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider tests\test_pvfs_shutdown_state_machine.py tests\test_managed_pvfs_sink.py tests\test_runtime_shutdown_integrity.py
```

Then from `C:/Users/ahoang/Morelia` run:

```powershell
& 'C:\Users\ahoang\vue-dashboard\backend\venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider tests\test_shutdown_protocol.py tests\test_shutdown_worker.py tests\test_watchdog_lifecycle.py
```

Expected: all focused tests pass; no process or DB residue exists outside
pytest-owned paths.

### Failure handling

Retain the pytest failure directory and print the last action per actor, process
PIDs/exit codes, missing required phases, embedded catalog row counts, and temp
DB inventory. Stop; do not add retries or mark the packet complete.

### Handoff

Provide exact commands/counts, successful and failed transcripts, process
PIDs/exit codes, and the remaining Packet 32 artifact and hardware gates.

## Definition of done

This packet is complete only when Units 1–6 pass and their closeout evidence is
appended here. Packet 32's spawned artifact gate and the real Pod8401HR hardware
gate remain required before release. The external pypvfs repository work remains
blocked and separate.

## Closeout evidence — 2026-07-29

Units 1–6 were implemented serially.

- Unit 1: 7 protocol reducer tests passed. Exported `ShutdownPhase`,
  `ShutdownOutcome`, `ShutdownActor`, `ShutdownAction`, `ShutdownSnapshot`,
  `ShutdownProtocol`, and `reduce_shutdown`; stable failure reasons include
  `protocol_violation`, `worker_exit_nonzero`, `forced_termination`, and
  `transcript_overflow`.
- Unit 2: 12 worker/reporting tests passed. The worker emits source, sink, and
  exit acknowledgements through a parent-owned queue; broad shutdown exception
  conversion to exit code zero was removed.
- Unit 3: 23 reducer/worker/watchdog lifecycle tests passed. The shared
  coordinator enforces one absolute deadline, drains post-exit actions, records
  forced termination, and returns per-stream bounded transcripts.
- Unit 4: 20 managed-PVFS tests passed, including writer-process evidence for
  stop, drain, native flush, native close, and catalog verification. The
  prescribed combined run also exposed two pre-existing dirty-worktree fixture
  failures in `test_sink_worker_ownership.py`: its `_FakeDataFlow` does not
  accept the already-present `on_source_error` argument in the user-modified
  runtime. That fixture was outside Unit 4's exact edit set and was not changed.
- Unit 5: 16 runtime transcript/multi-sink tests passed. Every transcript action
  is logged once, followed by a structured summary; forced or incomplete stops
  raise without emitting a `STOPPED` report.
- Unit 6: 2 spawned-process tests passed. The clean path produced exit code 0,
  `pvfs_catalog_verified` before `all_sinks_closed`, independent channel
  readback, unchanged pre/post SHA-256, and no `temp_*.db3` residue. Injected
  catalog verification failure produced non-zero exit evidence and no clean
  completion.

The Packet 32 independent artifact gate and the real Pod8401HR hardware gate
remain required before release. Existing July 21 artifacts were not touched.
