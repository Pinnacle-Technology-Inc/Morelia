# Support all requested Morelia sink types: design and system-gap audit

Status: Proposed; ready for implementation packetization  
Date: 2026-07-20  
Scope: backend control plane and its editable Morelia dependency  
Requested sink keys: `csv`, `edf`, `influx`, `plot`, `pvfs`, `quest`

## 1. Executive conclusion

The backend does not currently have a generic sink system with a CSV implementation. It has a
CSV-shaped configuration, manifest, path-allocation, recovery, CLI, and runtime path. Supporting the
five additional requested sink keys therefore requires a contract change across configuration,
persistence, process reconstruction, output safety, dependency preflight, operator UX, and tests.

Adding enum and registry entries alone is unsafe:

- Morelia's `EDFSink` deletes an existing destination when opened. Reconstructing it at the same
  path can destroy the pre-recovery recording.
- `PvfsSink` creates structured output and may own another writer process. Safe reopening after a
  stream or watchdog-process crash is not established.
- InfluxDB and QuestDB are services, not files; forcing them through `sink_location` gives them an
  invalid filesystem lifecycle.
- `PlotSink` is only the producer half of a GUI feature. `PlotDisplay` requires a Qt event loop in an
  interactive main process, while this backend runs Morelia inside a supervised background watchdog
  process.
- Influx credentials must not be persisted in session JSON, runtime manifests, exported templates,
  reports, or logs.

The confirmed shape is a typed, one-to-many source-to-sink configuration with capability-specific
validation and one runtime sink factory. Each source owns one or more ordered sinks; every sink
belongs to exactly one source and has a stable identity within that source. CSV remains backward
compatible. EDF and PVFS continue the same logical recording after error recovery. The installed
libraries failed the safe-reopen probes, so the current target always creates a linked new file; a
future same-file path may be enabled only by a version/platform-specific proof. Linked files are
format-aware merged into one published file after acquisition completes. A user stop immediately
marks that logical recording acquisition-complete; clicking start again creates a separate output,
independent of prior-file finalization. Influx and Quest reconnect to remote services through a new
bounded raw-sample delivery outbox. `plot` means a browser-visible Vue live plot, not a native Qt
window.

This document deliberately covers exactly the six requested keys. Morelia also exposes `BufferSink`
and `UDPSink`; those are out of scope unless separately requested.

## 2. Authority and evidence

### Intended behavior authority

Until this proposal is accepted, the authoritative tracked design remains:

- `docs/backend-control-plane-architecture-plan.md`: the first slice supports only managed CSV and
  defers other sinks until they are output-safe.
- `docs/system-audit-implementation.md`: task 7d defers output-safe non-CSV sinks, specifically EDF.
- `docs/stage4/README.md`: reconstruction must never truncate, overwrite, or delete prior output.
- This document: proposed expanded contract and acceptance behavior for the six requested sink keys.

### Current implementation authority

- `app/domain/enums.py`: `SinkType` contains only `csv`.
- `app/services/registry.py`: the sink registry contains only CSV with optional `file_path`.
- `app/services/session_config.py`: session entries accept `sink_type` and `sink_location`; arbitrary
  sink parameters are rejected and not round-tripped.
- `app/services/manifests.py`: every sink receives a filesystem location and collision handling.
- `app/runtime_host/manifest.py`: every `DeviceFlow` requires one non-empty `sink_location`.
- `app/runtime_child/morelia.py`: every stream rejects non-CSV types and builds
  `ManagedCsvSink` directly.
- `app/output/managed_csv_sink.py`: CSV has the only managed recovery-safe sink implementation.
- `app/output/boundaries.py`: a recovery-boundary helper exists, but repository search finds no
  production call site; only tests invoke it.
- `app/runtime_host/watchdog_process_driver.py` and `app/watchdog_process/__main__.py`: the runtime
  host spawns a watchdog process; the watchdog process constructs `MoreliaRuntime`; Morelia then
  spawns one collection worker per device stream.
- The inspected Morelia `source.py` sends sink subscription errors to `print()` only. Because the
  independently injected health sink can continue receiving samples, destination failure is not
  proven to make a stream unhealthy.

### External runtime authority

The inspected Morelia checkout is `C:/Users/ahoang/Morelia`, branch
`test-window-object-changes`, commit `80a1662` plus uncommitted changes. Relevant sink classes are in
`src/Morelia/Stream/sink/`. The sink files themselves were not reported modified, but `data_flow.py`,
`source.py`, and watchdog reconstruction code are modified. Runtime conclusions involving those
files must therefore be tied to the working tree, not only commit `80a1662`.

### Repository health

Observed on 2026-07-20:

- The backend worktree already contains many unrelated modified files, including
  `app/runtime_child/morelia.py`, plus untracked files. This proposal must not overwrite those edits.
- `.gitignore` no longer ignores `docs/` or `tests/`. This document and the local test directory are
  visible to Git as untracked content but are not staged or committed.
- `git ls-files tests` still returns no tracked tests. Test evidence is now eligible to enter version
  control, but it is not reproducible from the repository until the intended tests are selectively
  added and the unrelated local files are reviewed.
- The Morelia checkout is also dirty. Integration work must pin or record the exact Morelia revision
  and relevant working-tree diff before release evidence is accepted.

## 3. Terminology and scope

### Sink categories

| Sink type | Category | Durable output | External dependency | Recommended recovery strategy |
|---|---|---:|---|---|
| `csv` | file | yes | filesystem | reopen same managed file in append mode |
| `edf` | file | yes | filesystem, `pyEDFlib` | current version: linked continuation file, then format-merge; same-file resume only behind a future capability proof |
| `pvfs` | structured file/directory | yes | filesystem, `pvfs_tools`, native library | current version: linked continuation output, then format-merge; same-output resume only behind a future capability proof |
| `influx` | remote service | external | InfluxDB and credentials | reconnect; expose gap/delivery state |
| `quest` | remote service | external | QuestDB ILP TCP endpoint | reconnect; expose gap/delivery state |
| `plot` | live presentation/data transport | no recording by itself | browser channel | reconnect/reattach presentation consumer |

### In scope

- One source/device flow owns a non-empty ordered collection of configured sinks. A sink belongs to
  exactly one source, while a source may own several sinks, including multiple instances of one type.
- Stable sink identity, per-sink configuration, health, incidents, output metadata, and recovery
  evidence within a source stream.
- Sink-specific validation, canonicalization, import/export, manifest serialization, hashing, runtime
  construction, preflight, lifecycle, recovery, and operator errors.
- Backward-compatible CSV session input.
- No-overwrite behavior for file sinks.
- Format-aware, crash-safe finalization of fallback EDF/PVFS segments into one published output.
- Secret references rather than persisted secret values.
- Automated unit, process-boundary, and integration test definitions plus hardware/runtime gates.

### Out of scope

- Sharing one sink instance/destination owner across several sources. A shared remote server may be
  addressed by several distinct sink configurations, but each configured sink instance has one
  source owner.
- `BufferSink`, `UDPSink`, and arbitrary custom Python sink classes.
- Treating Plot as durable recording.
- Silently falling back from a requested sink to CSV.
- Reusing an EDF or PVFS output after a crash without a proven format-specific append contract, or
  merging segments through raw byte concatenation.

## 4. Proposed public configuration contract

Replace the flattened sink fields on each device flow with a non-empty `sinks` list. Each sink uses
the existing field names inside its own object, adds a stable user-visible `sink_name`, and carries
its own `sink_parameters`:

```toml
[[device_flows]]
nickname = "bench-a"
device_template_path = "device-templates/pod8206hr.toml"

[[device_flows.sinks]]
sink_name = "quest-live"
sink_type = "quest"

[device_flows.sinks.sink_parameters]
host = "localhost"
port = 9009
measurement = "experiment_a"

[[device_flows.sinks]]
sink_name = "browser-plot"
sink_type = "plot"
```

General rules:

1. `sinks` is required after canonicalization and contains at least one entry.
2. `sink_name` is non-empty and unique within its owning source. It defaults to the sink type when
   unambiguous; repeated types receive a deterministic suffix during guided creation.
3. `sink_type` is required and canonicalized to lowercase.
4. `sink_location` is permitted only for `csv`, `edf`, and `pvfs`.
5. File sinks may omit `sink_location`; the manifest resolver allocates a safe type-appropriate path.
6. Service and plot sinks reject `sink_location` rather than ignoring it.
7. `sink_parameters` defaults to `{}` and rejects unknown keys.
8. File locations are unique across every sink in the manifest, not merely within one source.
9. Canonical exports include only non-secret configured values and secret references.
10. Sink order is preserved for stable templates and diagnostics but is not used as identity.
11. Every sink's identity and canonical parameters participate in session/template round trips and
   manifest hashing.
12. A configuration error identifies the sink name/type, parameter, expected constraint, and source
   nickname without exposing credential values.

### Backward compatibility

Legacy device-flow entries containing top-level `sink_type`, optional `sink_location`, and optional
`sink_parameters` normalize into a one-element `sinks` list. Existing CSV input therefore remains
valid. New exports always use `sinks[]`; readers accept both shapes during the migration window and
reject entries that mix the flattened and list forms.

### Per-type parameter schemas

| Sink | Required parameters | Optional parameters | Runtime-only values |
|---|---|---|---|
| CSV | none | `observe_on_scheduler` | allocated/resolved path, managed output identity, field names |
| EDF | none | `observe_on_scheduler` | allocated segment path, segment identity, POD |
| PVFS | none | `observe_on_scheduler`, `use_writer_process`, `device_preferences` | allocated segment path, process objects, POD |
| Influx | `api_token_env` | `url`, `org`, `bucket`, `measurement`, `observe_on_scheduler`, `buffer_max_age_seconds`, `buffer_max_bytes` | resolved token, client/writer, POD, sink delivery outbox |
| Quest | none | `host`, `port`, `measurement`, `observe_on_scheduler`, `buffer_max_age_seconds`, `buffer_max_bytes` | socket, reactive subject, POD, sink delivery outbox |
| Plot | none | `chunk_samples`, `max_display_rate`, `channel_names` | transport queue/channel, source identity, POD |

Defaults should match the inspected Morelia constructors unless the product deliberately chooses
safer deployment defaults. Validate at least:

- non-empty host, URL, organization, bucket, measurement, and environment-variable name;
- TCP port in `1..65535`;
- positive `chunk_samples` and `max_display_rate`;
- positive service-buffer age and byte bounds; overflow policy is fixed to `drop_oldest`;
- `observe_on_scheduler` in `{null, "thread_pool", "new_thread"}`;
- `channel_names` as a non-empty list of non-empty strings;
- boolean `use_writer_process`;
- JSON-serializable `device_preferences` with a separately pinned schema before enabling it.

### Secrets

`api_token_env` names an environment variable; it is not the token. The watchdog process resolves it
immediately before constructing the Influx sink. Missing/empty variables fail preflight with the
variable name but not its value.

A backend wrapper around `InfluxSink` should preserve `api_token_env` in `get_dict()` and resolve the
value again during worker reconstruction. This avoids placing the token in Morelia's in-memory
snapshot dictionary. The wrapper and all report/log serializers must denylist or omit fields named
`api_token`, `token`, `password`, or `secret`.

## 5. Runtime manifest v2

Replace CSV-shaped fields with a typed nested sink collection:

```json
{
  "device_id": "pod8206hr:1234",
  "name": "pod8206hr",
  "nickname": "bench-a",
  "hardware_id": "1234",
  "port": "COM3",
  "parameters": {"preamp_gain": 10},
  "sinks": [
    {
      "sink_id": "pod8206hr:1234:quest-live",
      "name": "quest-live",
      "type": "quest",
      "parameters": {
        "host": "localhost",
        "port": 9009,
        "measurement": "experiment_a"
      }
    }
  ]
}
```

For file sinks, canonical sink parameters additionally contain the resolved absolute `file_path`.
Runtime-only objects, resolved secrets, queue handles, clients, sockets, and POD instances never enter
the manifest.

Required changes:

- Add a frozen `SinkConfig` value object with strict `to_dict()`/`from_dict()` behavior.
- Change `DeviceFlow` to own `sinks: tuple[SinkConfig, ...]` with at least one sink, unique per-source
  sink IDs/names, and globally unique file locations.
- Add the durable session identity needed to associate output segments and recovery gaps with their
  session. Persisted runtime manifests require it; side-effect-free previews may use `null`.
- Increment `MANIFEST_SCHEMA_VERSION` from `1` to `2`.
- Continue reading v1 manifests by translating `{sink_type, sink_location}` into a one-element CSV
  `SinkConfig` collection.
  New manifests are always written as v2.
- Include the entire ordered canonical sink collection in the content hash.
- Reject secret values and unknown parameters during manifest deserialization.
- Preserve strict stored-hash validation after v1 normalization and for native v2 documents.

Backward reading is release-critical because runtime-host adoption and watchdog respawn reuse persisted
manifests. A strict v2-only reader would make an in-flight CSV session unrecoverable during upgrade.

## 6. Runtime construction and dependency preflight

Create one sink factory owned by the runtime layer, for example:

```text
build_sink(sink_config, pod, runtime_context) -> SinkInterface
build_sinks(device_flow.sinks, pod, runtime_context) -> list[SinkInterface]
```

`runtime_context` supplies dataflow ID, manifest hash, device ID, output/segment allocator, secret
resolver, and plot transport. Use an explicit `match` on `SinkType`; six cases do not justify dynamic
class loading or arbitrary imports.

The Morelia import boundary should return device/dataflow types separately from type-specific sink
imports. Missing optional/native dependencies must disable only their sink type and produce a typed
preflight error. `ensure_morelia_ready()` should verify all selected sink-type requirements rather than
claiming all sink types are available because the base driver imported.

Sink execution errors need a real cross-process contract. Morelia currently prints subscription
errors, which can leave acquisition and the injected health sink running after the requested output
sink has stopped. The worker must publish sink identity, failure type, last successful delivery/write,
and terminal/degraded state to shared status. The watchdog must classify destination failure
separately from serial-port/source failure and must not report healthy solely from source heartbeats.
One failed sink must be identifiable even while sibling sinks on the same source continue receiving
data. If recovery still requires restarting the entire source worker, every sibling sink must survive
that reconstruction according to its own recovery contract.

### File sinks

#### CSV

Keep `ManagedCsvSink` behavior unchanged:

- exclusive first create;
- append-only same-file reconstruction;
- schema-hash check;
- one header;
- output metadata and byte/row offsets updated;
- foreign file never reused.

#### EDF

Do not instantiate Morelia's raw `EDFSink` against the logical configured path. Add a managed adapter
that allocates an exclusive segment before constructing the writer.

- First segment may use the configured path.
- An error-triggered recovery continues the existing logical recording. With inspected
  `pyedflib 0.1.42`, opening an existing path with `EdfWriter` silently replaced the original samples;
  Morelia's `EDFSink` also explicitly deletes that path. Therefore allocate a monotonically indexed
  continuation such as `recording.recovery-0001.edf` and link it to the previous segment. Same-file
  continuation is disabled unless a future library/version/platform probe proves preservation.
- A fallback segment stores the same logical sink ID, its own output ID and index, and an explicit
  `previous_output_id`. For example, `B_1.edf` points back to `B.edf`; it never replaces or mutates
  `B.edf` while collection is active.
- A clean user stop or other terminal recording completion closes all writers and marks acquisition
  complete. It requests a format-aware merge when more than one segment exists. The user may start the
  same hardware again immediately; that start creates a separate output file and logical output
  identity and does not resume or wait for the prior output.
- The merger reads each segment through an EDF-aware library, validates compatible headers/channels/
  sample rates and ordering, and writes a new temporary EDF. Raw byte concatenation and destructive
  reopen are forbidden.
- Publish the merged artifact only after readability, expected sample counts, ordering, and durable
  metadata are verified. Keep the component files untouched until publication and catalog commit both
  succeed. Retain superseded components for a configurable recovery period, then delete them through a
  separate cleanup job; cleanup is not part of the merge transaction.
- Merge is idempotent and fenced by logical-output/finalization identity. A crash or validation failure
  leaves the components recoverable and reports `merge_pending` or `merge_failed`; it must never claim
  that one-file finalization succeeded.
- The adapter's `get_dict()` carries the logical sink ID and next segment index, not permission to
  delete/reuse the old path.
- If the prior writer did not close cleanly, retain the prior file byte-for-byte and mark it
  `interrupted`; never delete it while starting the next segment.
- Validate both Pod8206HR and Pod8401HR channel headers/sample rates.
- Report buffered-data loss if forced termination prevents final EDF flush.

#### PVFS

Add a managed adapter with the same error-continuation/user-stop/finalization rule. The installed
`pvfs_tools` writable-open probe returned success but replaced the original `0..9` values with
`10..19` and then exposed `10..19` twice. Calling `PvfsDataFile.create()` on an existing copied
container also erased its channel data. Therefore the current target always creates a new exclusive
continuation output such as `B_1.pvfs`; same-output append is disabled unless a future capability probe
passes. At terminal completion, use PVFS-aware APIs to produce and verify one published output; never
concatenate raw containers. It additionally must:

- prove whether `.pvfs` is a file or directory for collision/allocation purposes on each platform;
- own and stop the optional PVFS writer subprocess before marking the segment closed;
- bound or monitor its currently unbounded writer queue;
- report queue backlog/drop and forced termination;
- never allow the runtime host, watchdog process, collection worker, and PVFS writer to believe they
  independently own the same segment;
- fail preflight when `pypvfs` or its native library cannot load.
- preserve all component outputs and expose retryable merge state if format-aware finalization is not
  supported on the target platform or fails validation.

### Service sinks

#### Influx

Use a wrapper that resolves `api_token_env`, constructs `InfluxSink`, and reconstructs without
serializing the token. Preflight validates configuration and dependency availability, resolves the
credential in the watchdog/worker boundary, and proves endpoint readiness before the session may enter
`running`. If the deployment cannot perform its configured non-destructive connection/write readiness
check, start fails rather than treating availability as unknown-success.

Define delivery semantics explicitly:

- connection refusal during start fails the session start;
- failure after start immediately warns the operator, makes that sink degraded, and opens an incident
  while source acquisition and healthy sibling sinks continue;
- persist unsent raw samples to a dedicated per-source/per-sink delivery outbox bounded by both age and
  bytes; reconnect drains it in sequence and acknowledges rows only after destination acceptance;
- when either bound is reached, drop the oldest outbox samples, increment durable permanent-loss
  counters, and remain visibly degraded;
- recovery reconnects with the same bucket/measurement and records a gap;
- retries must not busy-loop;
- the operator can distinguish source/hardware failure from destination failure;
- exactly-once delivery is not claimed unless an idempotency strategy is added and tested.

The existing `WatchdogOutbox` cannot satisfy this requirement. **Observed:** it stores
`RuntimeReport` telemetry envelopes containing device status and diagnostics, and repository logging
rules forbid raw samples. It has no raw measurement payload from which an Influx/Quest write can be
reconstructed. Implement a separate bounded `SinkDeliveryOutbox`; do not overload telemetry rows.
Samples still present in that delivery outbox are delayed, not lost, and are replayed after reconnect.
Samples evicted from it are permanently lost and must not be described as retrievable.

Initial defaults are 300 seconds and 256 MiB per sink, with the first reached limit winning. Both are
deployment-configurable and a deployment-wide disk cap must prevent the sum of sink outboxes from
exhausting the watchdog filesystem. Overflow always evicts the oldest samples and emits a warning plus
durable lost-sample/byte counters.

#### Quest

Apply the same delivery-outbox, lifecycle, health, retry, and operator-visible rules to the ILP TCP socket. Prove the
endpoint is reachable during preflight and fail start if readiness cannot be established. Because Morelia buffers
approximately half a second of samples before a socket send, forced termination can lose buffered
samples; report that risk rather than claiming clean delivery.

### Plot

Confirmed decision: `plot` publishes live samples to a browser data channel consumed by the Vue
dashboard. It must not start `PlotDisplay`/Qt inside the background watchdog process.

That choice requires a bounded live-data path distinct from low-rate watchdog telemetry:

- decimate and bound samples in the collection worker;
- carry a stable runtime/device/source identity;
- publish across the worker -> watchdog -> backend -> browser boundaries;
- apply backpressure or drop-oldest behavior so a slow/disconnected browser cannot stall acquisition;
- authenticate/authorize the browser subscription;
- expose disconnected/degraded presentation state without marking durable recording successful;
- close queues and subscriptions on stop, watchdog replacement, and runtime adoption.

Native Qt is out of scope for this sink key. If added later, it must be a separately named,
foreground-only mode with an explicit GUI owner and lifecycle.

The inspected Morelia `PlotSink.get_dict()` always emits the default `max_display_rate` instead of the
configured value. The backend must wrap/fix that reconstruction contract before non-default rates are
supported.

## 7. Output metadata and recovery boundaries

The existing `OutputFile` model can represent one physical output path but not a logical recording
with several physical segments. Extend the persistence contract so every file segment has:

- unique `output_id`;
- stable `logical_sink_id`;
- `segment_index` unique within the logical sink;
- `previous_output_id` for continuation segments and `final_output_id` after publication;
- sink type, path, schema hash, status, timestamps, byte/row offsets where meaningful;
- termination reason such as `clean`, `recovery`, `watchdog_crash`, `forced`, or `writer_failure`.

Separate acquisition state from artifact state. Acquisition is `open`, `interrupted`, or `complete`;
a user stop transitions it to `complete` as soon as all writers close. Artifact state is
`not_required`, `merge_pending`, `merging`, `merged`, or `merge_failed`. A merge attempt carries a
unique finalization ID so retries and competing workers cannot publish twice or delete evidence still
needed by another attempt.

For CSV, one physical output normally remains one logical sink. For EDF/PVFS, an error-interrupted
logical sink may own multiple linked physical segments. A user stop marks acquisition complete and
triggers background finalization; when multiple segments exist, successful finalization publishes one
verified merged output. A later start immediately allocates a new logical sink output and physical
file even when prior finalization is pending or the session/source config is otherwise unchanged.

The control plane owns a durable finalization job and exclusive claim; a dedicated finalizer process
performs format I/O only after every writer for the logical output is closed and fenced. It writes to a
temporary path on the same filesystem, verifies the artifact, atomically publishes it where supported,
then commits `final_output_id`. If publish or metadata commit fails, the control-plane reconciler safely
retries from retained components. Operator status distinguishes acquisition completion from artifact
merge completion. Finalization never owns hardware and cannot block a new recording on that device.

Stop overloading `RecoveryGap.previous_segment_id` and `next_segment_id` with undocumented offset-only
JSON. Define a versioned boundary payload or normalized boundary rows that can express:

- same-file boundary: output ID plus pre/post byte and row offsets;
- segmented boundary: previous and next output IDs;
- remote sink boundary: destination identity plus last confirmed/first resumed timestamp if known;
- plot boundary: presentation disconnect/reconnect timestamps, if product-relevant.

Do not invent offsets or delivery confirmations when evidence is missing.

Wire boundary persistence into the production recovery path. The existing helper's docstring says the
Morelia driver calls it, but no production caller exists. The chosen owner must receive the durable
session ID, logical sink ID, recovery ID, and pre/post evidence for both automatic Morelia recovery
and whole-watchdog respawn. A unit test that calls the helper directly is not production proof.

## 8. API, CLI, templates, and operator behavior

### API/session services

- Add non-empty `sinks[]` and nested `sink_parameters` to accepted session/template shapes, with
  legacy flattened sink input normalized to a one-element list.
- Return canonical non-secret sink parameters in session preview/show/export responses.
- Reject wrong-category fields (`sink_location` on Quest, `api_token_env` on CSV).
- Make sink override behavior file-sink-only; remote and plot sinks must not enter the filename-conflict
  retry loop.
- Address file-conflict overrides by source nickname plus `sink_name`; source nickname alone is
  ambiguous once one source owns several file sinks.
- Keep errors typed and stable for clients: unsupported sink, invalid parameter, dependency missing,
  secret missing, destination unavailable, output collision, output not writable, and GUI/browser
  transport unavailable.

### CLI

- For each selected source, the guided create quiz asks for a sink type, prompts only that type's
  parameters, shows the configured sink, and asks whether to add another sink. It requires at least
  one sink and permits repeated sink types with unique sink names.
- File sinks retain blank-for-system-assigned location behavior.
- Influx asks for an environment-variable name, never the token value.
- The quiz summary groups all sinks under their source and offers edit/remove/add before submitting.
- Template-based flows load every sink, preserve its name/type/location/parameters, and allow each to
  be kept, edited, removed, or supplemented. Removing the last sink is rejected.
- Preview prints the canonical sink configuration with secret references only.
- Start/watch output distinguishes `source`, `sink`, and `transport` health/failure domains.

### Template import/export

- Store complete sink information in session templates: ordered `sinks[]`, `sink_name`, `sink_type`,
  optional `sink_location`, and nested `sink_parameters`.
- Support nested sink lists/parameters in TOML and JSON while reading legacy flattened templates.
- Preserve stable ordering and types for strings, integers, booleans, arrays, and nested
  `device_preferences` if enabled.
- Round-trip every supported sink configuration.
- Never export resolved secrets or runtime-only parameters.

## 9. Process and ownership boundary map

```text
CLI/API request
  -> session JSON + source with canonical sinks[] (control-plane database)
  -> manifest resolver + runtime manifest v2 (control plane)
  -> runtime host subprocess (manifest file)
  -> watchdog subprocess (re-reads manifest; owns MoreliaRuntime)
  -> Morelia DataFlow collection worker per source/device
       -> every owned sink reconstructed from sink.get_dict() + pod
       -> optional PVFS writer subprocess
       -> optional bounded plot transport publisher
       -> durable linked EDF/PVFS segment metadata
       -> per-service-sink raw `SinkDeliveryOutbox` -> ordered destination replay/ack
  -> control-plane durable finalization job -> dedicated finalizer process after all writers close
       -> verified temporary artifact -> fenced publication -> final output metadata
  -> reports/outbox/direct ingest back to control plane
  -> SSE/CLI status and optional browser plot channel
```

Ownership rules:

- The control plane owns session/manifest/output/gap metadata and operator-visible state.
- The runtime host owns watchdog-process identity, adoption, and respawn budget, but not sink handles.
- The watchdog process owns `MoreliaRuntime`, sink factory context, and secret resolution.
- Each DataFlow worker owns the live sink handle/socket/writer for its stream.
- Each configured sink has one source owner and one stable sink ID. One source worker may own several
  live sink instances; no sink instance is shared between source workers.
- Each Influx/Quest collection worker is the sole live writer/drainer for its sink delivery outbox.
  The outbox path is keyed by durable session/source/sink identity rather than watchdog-process ID so
  a fenced replacement worker can adopt pending samples after a crash. Telemetry outbox identity and
  retention remain separate.
- Worker-side output metadata currently uses a minimal Flask/SQLAlchemy application against the
  shared control-plane database. If retained, segment allocation and state transitions must be atomic
  under concurrent SQLite writers and must carry the real session ID.
- A PVFS writer subprocess, when enabled, owns PVFS native I/O only; its parent collection worker owns
  its lifecycle and queue.
- A browser plot consumer never owns acquisition and cannot block or stop the source stream merely by
  disconnecting.
- No process may reopen or create a file segment until it has a durable logical/physical output claim.
- No finalizer may read/publish a logical output until every writer is closed and a durable exclusive
  finalization claim fences stale or concurrent attempts. The control plane owns the job, claim,
  reconciliation, and catalog commit; the dedicated finalizer process owns only one merge attempt and
  temporary file handles.
- A collection worker detects live sink errors, the watchdog converts them to sink-specific durable
  telemetry, and control-plane ingest owns recovery-boundary/output-state persistence before it issues
  any recovery command.
- Descriptor construction in the watchdog process must not leave a second live file handle or service
  client beside the worker-owned sink. Today `ManagedCsvSink` opens its managed file during parent
  construction and the worker reconstructs another instance; that ownership needs explicit closure
  or deferred-open behavior.

## 10. Five release-critical scenarios

| Scenario | Initial durable state | Action | Expected state/ownership/result | Forbidden result | Verification |
|---|---|---|---|---|---|
| First start for a multi-sink source | Valid session; one source has one or more sinks; no active runtime; file paths free and services configured | Start session through normal API/CLI path | Manifest v2 persists ordered sinks; watchdog constructs all; one worker owns every sink for that source; start fails atomically on invalid dependency/secret/destination | only a subset starts; remote sink treated as path; two sinks share one identity/path; partial claims remain active | registry/config/template/manifest tests; real subprocess start; service/file integration; hardware lane |
| Error-triggered source recovery | Active source and sibling sinks have produced/delivered data | Sink/source error causes watchdog to reconstruct the source worker | same logical recording continues; current EDF/PVFS always create linked continuation files; services reconnect and replay bounded delivery outboxes; browser plot reattaches; each sink records status/gap | prior output deletion/truncation; sibling sink identity swap; two writers; secret exposure; telemetry outbox mistaken for raw replay; unbounded retry; healthy status without sink proof | per-sink reconstruction plus mixed-sink test; byte/readability checks; subprocess outage/replay test; hardware recovery |
| Fallback-segment finalization | Closed EDF/PVFS logical output owns `B` plus one or more linked `B_n` continuation files | Finalization owner claims the logical output and performs a format-aware merge | one verified final artifact is published; component files remain until publish and catalog commit succeed; status becomes `merged`; retry is idempotent | raw concatenation; component deletion before proof; concurrent merger; duplicate/reordered samples hidden; success reported for unreadable output | library/consumer readability and sample-order checks; merge-worker crash/fault injection; concurrent claim test; retry test |
| Clean user stop then immediate later start | Active source and sinks are healthy | User stops and clicks start again, possibly while prior finalization is pending | prior acquisition becomes `complete` after writers close; finalization continues independently; new start creates a new logical/physical output and new remote/plot connections on the same hardware | new run resumes old output; new start waits on unrelated merge; finalizer owns hardware; merge success claimed early; old clients/queues remain owners | CLI/API lifecycle race test; merge/acquisition state and DB identity assertions; filesystem/readability checks; hardware lane |
| Watchdog crash and respawn | Active runtime host/watchdog and multi-sink source have produced data | Kill watchdog process; runtime host detects and respawns | new watchdog identity reads same manifest; every sink follows error-continuation semantics; stale reports fenced; per-sink gaps/loss visible | only one sink restored; old/new writers overlap; user-stop semantics applied to crash; plot GUI spawned; silent remote loss | real process-tree kill test; durable per-sink assertions; stale identity test; hardware/runtime capture |

## 11. Test strategy and quality gates

### Cheapest automated proofs

1. Registry table tests for all six types: defaults, required/unknown fields, coercion, invalid values,
   wrong-category location, and hashable canonical specs.
2. Session/template TOML and JSON round trips for one and several sinks per source, repeated sink
   types, stable sink identities/order, legacy flattened input, and secret-value rejection/redaction.
3. Manifest v1 CSV compatibility plus native v2 round trip/hash/tamper tests.
4. Sink-factory tests using injected fake classes, proving the complete ordered sink list, exact
   constructor kwargs, unique identities, and no eager optional dependency imports.
5. `get_dict()` reconstruction tests for every adapter/wrapper.
6. File negative tests: existing foreign file unchanged, pre-recovery bytes unchanged, segment index
   monotonic, partial initialization cleaned up, forced worker death never deletes prior output.
7. EDF/PVFS finalization tests: format-aware merge preserves channel metadata and chronological sample
   order; temporary/published paths are fenced; a merger crash, invalid segment, catalog failure, or
   retry never destroys components or publishes twice; successful output is readable by consumer tools.
8. Influx/Quest integration tests against disposable services: unavailable at start; immediate warning
   after an outage; age/byte and global disk caps; oldest eviction; exact loss counters; ordered replay
   and ack; watchdog death/adoption with pending samples; clean shutdown; no credentials in rows.
9. Real spawned-process tests across runtime host -> watchdog -> DataFlow worker. In-process mocks do not
   prove ownership, secret isolation, queue cleanup, or crash behavior.
10. Plot transport tests with a slow/disconnected browser: acquisition continues, bounded memory, old
   samples dropped according to policy, reconnect works.
11. Mixed-sink tests such as CSV + Influx + Plot on one source: one destination fails, sibling sinks
    continue, the failing sink becomes degraded, and whole-stream reconstruction preserves every
    sink's identity and recovery contract.
12. User-stop/immediate-restart tests prove acquisition becomes complete, background finalization can
    coexist without hardware ownership, and the next run receives new logical and physical identities.

### Hardware/runtime gates

- Pod8206HR and Pod8401HR first start/clean stop for each feasible sink.
- Targeted stream recovery while every file sink is writing.
- Watchdog-process kill/respawn while every file sink is writing.
- PVFS writer-process enabled at the intended highest sample rate.
- Influx/Quest destination interruption during acquisition against disposable services, including
  delivery-outbox replay and forced watchdog termination with explicitly reported in-memory loss.
- Confirm actual output readability with EDF/PVFS consumer tools, not merely path existence.
- Finalize multi-segment EDF/PVFS recordings on the target filesystem, including forced merger death
  and retry, and compare headers/sample counts/order against the component files.
- Plot/dashboard sustained run at the intended channel count and sample rate.

### Current baseline evidence

Executed on 2026-07-20:

```text
venv\Scripts\python.exe -m pytest -q \
  tests/test_registry.py tests/test_session_config.py tests/test_runtime_manifest.py \
  tests/test_managed_sink_append_on_recovery.py tests/test_watchdog_process_respawn.py \
  tests/test_watchdog_process_entrypoint.py

Result: 83 passed, 14 failed in 6.19s.
```

The failures include stale session/template assumptions, service-manifest failures downstream of
those assumptions, and one watchdog-entrypoint test whose stub config lacks a newly required setting.
They are pre-existing baseline/test-drift findings, not evidence about new sinks.

A narrower current-contract subset was green:

```text
venv\Scripts\python.exe -m pytest -q \
  tests/test_registry.py tests/test_managed_sink_append_on_recovery.py \
  tests/test_runtime_host_manifest.py tests/test_morelia_runtime_pod8401.py

Result: 56 passed in 3.05s.
```

This proves selected pure CSV/manifest/device-construction behavior only. It does not exercise a real
Morelia DataFlow worker, non-CSV sink, external service, native library, GUI/browser path, or hardware.

### Isolated EDF/PVFS recovery experiment

Executed on 2026-07-20 with the backend virtual environment, `pyedflib 0.1.42`, the installed
`pvfs_tools` package/native DLLs, and synthetic one-channel 10 Hz data. The probe created files only in
a uniquely named Windows temporary directory and removed that directory after the native handles were
released.

| Probe | Observed result | Evidence classification | Consequence |
|---|---|---|---|
| EDF open existing path with `pyedflib.EdfWriter` | call succeeded but original approximate `0..9` samples became approximate `100..109`; original hash/content was not preserved | `observed` | current same-file EDF continuation is unsafe and disabled |
| EDF format-aware merge | read two 10-sample segments and wrote a fresh EDF; merged file was readable with 20 ordered samples; both components remained | `observed` synthetic proof | read-and-rewrite merge is feasible, but multi-channel/header/crash/hardware proof remains |
| PVFS writable open then `append_block` | call returned `0` and reader exposed 20 samples, but values were `10..19` followed by `10..19`; original `0..9` data was overwritten | `observed` | current writable-reopen PVFS continuation corrupts data and is disabled |
| PVFS `create()` on existing copied container | call returned success, changed the file, and the original channel could no longer be opened | `observed` | Morelia's current create-on-reconstruction path is destructive |
| PVFS format-aware merge | read two 10-sample containers and wrote a fresh PVFS container; merged file was readable with 20 ordered samples; both components remained | `observed` synthetic proof | read-and-rewrite merge is feasible, but metadata/device preferences, multi-channel, crash, writer-process, and hardware proof remains |

The first probe's immediate cleanup encountered a delayed Windows PVFS file handle; cleanup succeeded
after the Python process exited and a short retry. This reinforces that finalization and cleanup must
be separate, retryable lifecycle steps. These probes are discovery evidence, not release-level runtime
or real-hardware verification.

## 12. Contract coverage matrix

| Behavior | Intended source | Production path | Boundary | Positive proof | Negative proof | Runtime proof | Status |
|---|---|---|---|---|---|---|---|
| CSV config and registry | current code/plans | enum -> registry -> session config | API/CLI -> DB | passing registry tests | unknown-field tests | none in this audit | partially_verified |
| CSV append on reconstruction | Stage 4 + managed sink | Morelia snapshot -> `ManagedCsvSink` | worker reconstruction -> DB/file | passing reconstruction tests | foreign-file/schema mismatch and byte-preservation tests | hardware evidence not rerun | partially_verified |
| Accept any requested non-CSV type | this proposal | same path as CSV today | config -> manifest | none | current enum/registry reject it | none | contradicted |
| Correct non-file configuration | this proposal | session -> manifest | DB/filesystem model | none | current mandatory location demonstrates mismatch | none | contradicted |
| EDF no-overwrite recovery | Stage 4 invariant + this proposal | raw Morelia EDF today | worker -> filesystem | synthetic format-aware segment merge succeeded | raw code deletes; direct existing-path writer probe replaced original samples | no worker/hardware proof | contradicted |
| PVFS safe recovery/process ownership | this proposal | raw Morelia PVFS today | worker -> writer child -> filesystem | synthetic format-aware container merge succeeded | writable reopen overwrote original values; create-existing erased channels; no duplicate-writer proof | no worker/hardware proof | contradicted |
| Influx secret isolation/reconnect | this proposal | raw Morelia Influx today | manifest/env -> worker -> service | constructor/get_dict inspected | token is currently returned by raw `get_dict()` | none | contradicted |
| Quest reconnect and loss visibility | this proposal | raw Morelia Quest today | worker -> TCP service | constructor/get_dict inspected | no retry/gap tests | none | unverified |
| Plot operator-visible output | this proposal | no backend data plane today | worker -> watchdog -> Vue/browser | raw queue/Qt implementation inspected | no backend browser consumer exists | none | contradicted |
| Watchdog crash preserves output by sink type | this proposal | runtime host respawn -> manifest -> new watchdog | multiple processes + durable output | identity/respawn unit tests | only CSV-specific output tests | hardware/non-CSV proof absent | partially_verified |
| Manifest upgrade preserves active CSV recovery | this proposal | persisted manifest -> host/watchdog readers | DB/file -> subprocess | current strict v1 parser tests | no v1-to-v2 compatibility exists | none | unverified |
| Destination failure changes sink health | this proposal | worker sink subscription -> watchdog report | worker -> watchdog -> control plane | none | current Morelia path prints subscription errors while source health may continue | none | contradicted |
| Recovery boundary is durably recorded | Stage 4 + this proposal | recovery -> `record_boundary` -> DB | worker/watchdog -> control-plane DB | helper unit tests | no production call site found | none | contradicted |
| One source owns several independently identified sinks | confirmed requirement | session/template -> manifest -> DataFlow network | API/DB -> worker sink list | raw Morelia accepts a list of sinks | backend config/manifest/runtime flatten to one sink | no backend runtime proof | contradicted |
| User stop creates a new output on later start | confirmed requirement | stop/close -> later manifest/output allocation | lifecycle -> DB/filesystem | current collision allocator can produce alternate path | no logical-output identity contract/test | no runtime proof | unverified |
| EDF/PVFS fallback segments become one final file | confirmed requirement | terminal close -> finalization claim -> format-aware merge -> publish/catalog commit | worker/filesystem/DB and finalizer process | synthetic EDF and PVFS ordered read-and-rewrite merges succeeded while preserving components | no production merger, fencing, fault injection, multi-channel, or metadata proof | synthetic library proof only | partially_verified |
| Remote samples replay after an outage | confirmed requirement | sink worker -> bounded `SinkDeliveryOutbox` -> destination | worker/local disk/service | existing telemetry outbox durability is tested for reports | existing outbox has no raw samples; no delivery spool/replay path exists | none | contradicted |

## 13. Gap register

| ID | Gap | Type | Evidence | Impact | Confidence | Required proof | Suggested owner/disposition |
|---|---|---|---|---|---|---|---|
| SINK-01 | Domain enum/registry reject five requested types | implementation | observed in enum and registry | feature cannot be configured | high: direct code | six-type validation tests | new config-contract packet |
| SINK-02 | Session/template contract cannot persist sink-specific parameters | specification/persistence | observed fixed entry fields and export keys | remote/plot sinks cannot be reconstructed | high: direct code | per-type round trips | new config-contract packet |
| SINK-03 | Manifest requires a path for every sink | specification/integration | observed `sink_location: str` invariant and allocation | non-file sinks are mis-modeled | high: direct code | v2 and v1 compatibility tests | manifest-v2 packet |
| SINK-04 | Runtime hard-codes `ManagedCsvSink` | implementation | observed explicit non-CSV rejection | accepted types would fail at preflight | high: direct code | injected factory tests | sink-factory packet |
| SINK-05 | Raw EDF reconstruction deletes/replaces prior recording | output safety | observed `os.remove` in `EDFSink.__enter__`; synthetic existing-path writer probe replaced original values | catastrophic data loss | high: direct code and library probe | managed continuation byte-preservation + crash/segment tests | managed-EDF packet; release blocker |
| SINK-06 | Current PVFS reopen/create paths corrupt or erase prior data; nested writer ownership is also unproved | process boundary/output safety | writable-open probe overwrote original values despite success; create-existing erased channels; optional writer child observed | corruption, duplicate writer, unflushed data | high: direct library probes plus static process trace | real managed-segment subprocess/hardware crash tests | managed-PVFS packet; release blocker |
| SINK-07 | Influx token would be persisted or exposed if raw parameters are copied | security/persistence | observed raw `get_dict()` returns token | credential disclosure | high: direct code | secret rejection/redaction and process tests | Influx wrapper packet; release blocker |
| SINK-08 | Influx/Quest destination failures are not separated from source health | observability/integration | no backend sink-health contract; raw sinks raise/send asynchronously | wrong recovery action and silent loss | medium: static evidence only | outage integration and report-schema tests | service-sink packet |
| SINK-09 | Backend has no Vue live-plot data plane for the confirmed browser Plot contract | state ownership/process boundary | Qt is unsuitable in the watchdog and no bounded worker-to-browser sample path exists | configured Plot would have no visible consumer | high: direct boundary trace plus confirmed decision | bounded browser transport prototype and disconnect/backpressure tests | Vue Plot data-plane packet |
| SINK-10 | Plot reconstruction resets non-default display rate | external dependency | observed `get_dict()` emits constant default | changed behavior after recovery | high: direct code | non-default reconstruction test | backend wrapper or Morelia fix |
| SINK-11 | Manifest schema upgrade can strand active v1 CSV sessions | lifecycle/migration | current reader accepts only exact current version | failed adoption/respawn during deploy | high: direct code | persisted v1 adoption/respawn test | manifest-v2 packet; release blocker |
| SINK-12 | File metadata does not model logical multi-segment outputs | persistence | one `OutputFile` row/path; offsets overloaded into gap string fields | incomplete recovery history and allocation races | high: direct schema | migration + concurrent segment allocation tests | output-segment packet |
| SINK-13 | Optional/native dependency readiness is not sink-specific | external dependency | current import/preflight path is CSV-oriented | one missing extra may fail late or broadly | medium: runtime env not fully audited | isolated dependency preflight tests on target OS | sink-factory/dependency packet |
| SINK-14 | Current sink tests are absent for five types and existing local tests remain untracked | test coverage | no focused Morelia sink tests; `tests/` is now visible but `git ls-files tests` is empty | required evidence has not yet entered version control or CI | high: git/test search | selectively track tests and run CI/runtime matrix | each implementation/test packet |
| SINK-15 | Current targeted baseline has 14 unrelated failures | test coverage/documentation drift | recorded pytest run | new failures cannot be cleanly attributed | high: executed evidence | repair/retire stale tests before feature gate | existing test-maintenance packet |
| SINK-16 | Backend and Morelia worktrees are both dirty/unpinned | repository hygiene/external dependency | observed git status | non-reproducible implementation and runtime proof | high: git evidence | clean/pin diffs or record immutable revisions | repository owner before release |
| SINK-17 | `device_preferences` has no pinned safe public schema | specification/security | raw Morelia accepts list of dictionaries | unstable/overbroad config surface | medium: content contract uninspected | inspect producer/consumer and define allowlist | defer parameter or separate packet |
| SINK-18 | Recovery-boundary persistence is not wired into production | integration/persistence | `record_boundary()` is referenced only by tests | recoveries can occur without durable gap/output boundary | high: repository-wide call-site search | real targeted recovery and watchdog-respawn DB assertions | output-segment/integration packet; release blocker |
| SINK-19 | Sink subscription errors are printed rather than reported as destination failure | observability/output safety | observed Morelia `source.py` `on_error=lambda e: print(e)` and separate health sink | silent output loss while source appears healthy | high: direct code; runtime manifestation still to prove | injected sink-failure worker test and external outage test | Morelia/runtime health-contract packet; release blocker |
| SINK-20 | Runtime manifest lacks durable session identity required by `RecoveryGap` and `OutputFile` | persistence/process boundary | `Manifest` has dataflow ID only; managed CSV is built without `session_id`; boundary helper requires it | orphaned output metadata and inability to record valid gap | high: direct constructor/schema trace | manifest-to-worker metadata assertion and FK-backed recovery test | manifest-v2 packet |
| SINK-21 | Parent watchdog and DataFlow worker can hold separate managed CSV instances/handles | process boundary/output safety | parent sink opens during `_build_stack`; DataFlow reconstructs it in worker; parent closes only on runtime stop | ambiguous writer ownership, flush/status races, harder segmented recovery | medium-high: static trace; handle behavior not runtime-tested | spawned worker handle/ownership test and deferred-open adapter proof | sink-factory foundation packet |
| SINK-22 | Backend flattens each source to one sink despite confirmed one-to-many domain cardinality | specification/implementation | session fields, manifest `DeviceFlow`, resolver, runtime, CLI, and templates expose one sink; raw Morelia accepts sink lists | cannot configure CSV + remote + Plot for one source | high: full path observed | canonical multi-sink round trip and real DataFlow worker test | typed config/manifest/runtime packets; release blocker |
| SINK-23 | Recovery and health are source-scoped but output evidence must be sink-scoped | state ownership/observability | recovery targets `device_id`/stream while multiple sink statuses/IDs do not exist | one failing sink can restart or obscure healthy siblings; gaps may be attached to wrong sink | high risk; high confidence from confirmed cardinality and current APIs | mixed-sink failure/recovery test with per-sink durable assertions | health-contract and recovery-integration packets |
| SINK-24 | Error continuation and user-stop restart do not have distinct logical-output transitions | lifecycle/output safety | current output model has open/closed only and no logical output/segment index | stopped recordings may be accidentally resumed or crash continuations split incorrectly | high: requirement has no model path | state-machine tests for error, forced stop, clean stop, later start | logical-output segment packet; release blocker |
| SINK-25 | Session template and guided create paths cannot express or edit a sink collection | interface/documentation drift | templates preserve flattened fields; quiz creates one default CSV/path | new cardinality is unusable from supported operator workflows | high: direct code | template API/TOML round trips and interactive quiz tests | config/CLI template packet |
| SINK-26 | No crash-safe production EDF/PVFS finalizer exists | output safety/state ownership/persistence | synthetic format-aware merges succeeded, but current model has one path and no finalization job/state, claim, temporary publication, or retention cleanup | a failed/concurrent production merge could lose, duplicate, reorder, or misreport data | high requirement risk; high confidence from schema/runtime trace and partial library proof | multi-channel metadata merge, fault-injection, fencing, idempotent retry, component retention, cleanup, and consumer/hardware tests | file-finalization packet; release blocker |
| SINK-27 | Existing watchdog outbox cannot replay raw Influx/Quest samples | persistence/integration/output safety | observed `WatchdogOutbox` stores `RuntimeReport` device-status/diagnostic payloads; raw samples are absent and forbidden by logging policy | destination outage data would be permanently lost despite the requested replay behavior | high: direct protocol/schema trace | separate bounded sink-delivery outbox tests for age/byte limits, oldest eviction, warning/loss counters, ordered replay, ack, restart, and disk exhaustion | delivery-outbox foundation packet; release blocker |

Confidence statements above distinguish direct code observations from risks that still require runtime
evidence. A high-confidence gap is not the same as a verified future fix.

## 14. Contradictions and orphaned findings

| Finding | Disposition |
|---|---|
| Existing architecture says CSV-only; requested scope says six types | Not a defect in old scope. Supersede only after this proposal is accepted and implemented. |
| Stage 4 says same-file append, while EDF/PVFS require segments with the inspected libraries | Experiments found EDF replacement and PVFS corruption on reopen. The current contract mandates linked files and a format-aware merged artifact; only a future version/platform capability proof may re-enable same-file continuation. Record the exception explicitly in the accepted architecture/ADR. |
| `RecoveryGap` segment columns currently contain JSON offsets | Requires a new persistence/boundary packet; do not silently overload further. |
| Morelia exports Buffer and UDP but request calls six types “all” | Explicitly rejected as current scope; revisit separately. |
| Tests and most docs were ignored even though local files are used as evidence | Fixed at policy level: both directories are now visible to Git. The intended specification and tests still need selective staging/review before their evidence is reproducible. |
| Requested remote-sample recovery refers to the watchdog outbox, but that outbox stores telemetry only | Preserve the telemetry contract and add a distinct bounded raw `SinkDeliveryOutbox` keyed by durable sink identity. Oldest samples evicted from that new outbox are permanent loss. |
| Morelia sink source looks unchanged but its process/recovery dependencies are modified | Treat the whole working tree as the runtime source until pinned; do not cite commit-only behavior. |

## 15. Candidate implementation boundaries

These boundaries are ready to be converted into execution packets by `work-packet-breakdown`; they are
not themselves full packet specifications:

1. **Typed multi-sink configuration**: enums, `sinks[]`, stable per-source sink identity, per-type
   validation, legacy normalization, canonical session/template import/export, and secret rules.
2. **Manifest v2 compatibility**: `SinkConfig`, hashing, v1 CSV translation, persisted-manifest tests.
3. **Sink-list factory and preflight**: explicit ordered construction, atomic failure cleanup, lazy
   dependency checks, typed errors, injected-class tests, unchanged legacy CSV behavior.
4. **Logical output segments**: persistence migration, atomic segment allocation, predecessor links,
   boundary representation, finalization states, cleanup/termination states.
5. **Managed EDF**: enforce linked continuation segments for the current library, reject destructive
   same-path reconstruction, clean-stop/new-output transition, crash safety, and readable-segment tests.
6. **Managed PVFS**: enforce linked continuation outputs for the current library, reject destructive
   create/reopen paths, writer-process ownership, queue policy, native preflight, and crash/flush tests.
7. **EDF/PVFS finalization**: format-aware mergers, exclusive/fenced finalization claims, temporary output,
   validation, atomic publication, idempotent retry, configurable component retention/cleanup, immediate
   new-recording independence, and operator-visible failures.
8. **Sink delivery outbox**: raw-sample schema, per-sink sequence/ack, age and byte bounds, 300-second/
   256-MiB defaults, oldest eviction, global disk cap, loss counters, restart replay, and telemetry
   separation.
9. **Influx**: secret-resolving wrapper, destination lifecycle, delivery-outbox replay, retry/health/gap
   reporting, disposable-service tests.
10. **Quest**: destination lifecycle, delivery-outbox replay, retry/health/gap reporting,
    disposable-service tests.
11. **Vue Plot data plane**: bounded worker-to-browser transport, authorization, backpressure/drop
   policy, reconnection, and consumer lifecycle.
12. **Per-sink health and source-scoped recovery**: mixed-sink failure aggregation, stable IDs,
     sibling continuity, and durable per-sink gap/loss evidence.
13. **Session template and create quiz**: expose the same canonical multi-sink contract in templates,
     preview, guided add/edit/remove flows, and conflict resolution.
14. **Cross-sink runtime gate**: real runtime-host/watchdog/DataFlow subprocess tests, hardware matrix,
     operator runbook, rollout and rollback.
15. **Documentation reconciliation**: update architecture, implementation roadmap, CLI examples, and
    support matrix only as each capability becomes real.

## 16. File-by-file change inventory

This is the expected edit surface. `work-packet-breakdown` should assign exact read/edit sets,
migrations, and tests while preserving the acceptance gates in sections 10 and 11.

| Area/file | Needed change |
|---|---|
| `app/domain/enums.py` | Add the five requested non-CSV enum values and any sink/output status enums. |
| `app/domain/errors.py`, `app/errors.py` | Add typed invalid-parameter, dependency, secret, destination, and segment-allocation errors plus stable HTTP mappings. |
| `app/services/registry.py` | Add capability-specific schemas/defaults/validators for all six sink types, including service-outbox age/byte limits and fixed oldest-eviction policy. |
| `app/services/session_config.py` | Accept/canonicalize non-empty `sinks[]`; assign/validate stable per-source names; apply per-sink file collision checks; normalize legacy flattened CSV input; serialize nested TOML/JSON safely. |
| `app/services/session_templates.py` | Preserve, validate, preview, import, and export every sink name/type/location/parameter set in each source's ordered sink list. |
| `app/api/schemas.py`, `app/api/sessions.py` | Replace raw/flattened sink shapes with typed source-with-sinks request/response schemas; reject secret values, duplicate identities/paths, and category mismatches. |
| `app/cli/session_cmd.py` | Add the per-source add/edit/remove sink quiz loop, type-specific parameters, unique naming, grouped/redacted previews, template sink editing, and sink-specific conflict handling. |
| `app/services/manifests.py` | Build every `SinkConfig`; allocate paths only for file sinks; enforce global location uniqueness; attach durable session identity; hash ordered canonical non-secret sink lists. |
| `app/runtime_host/manifest.py` | Implement manifest v2 `DeviceFlow.sinks` plus v1 one-CSV translation and strict hash/version behavior. |
| `app/control/supervisor.py` | Make driver readiness selected-sink-aware and preserve actionable dependency/preflight errors. |
| `app/watchdog_process/__main__.py` | Pass selected sink-list runtime context, secret resolver, and output-health reporting into `MoreliaRuntime`. |
| `app/runtime_child/morelia.py` | Replace CSV branch with ordered sink-list factory; pass the full list to each Morelia source; enforce one source owner per sink and one live process owner; expose per-sink health; wire targeted recovery and whole-process restart evidence. |
| `app/runtime_child/driver.py` and report/protocol schemas | Carry bounded per-source and per-sink health, buffer, loss, delivery, and output evidence without secrets or high-rate samples. |
| `app/output/managed_csv_sink.py` | Preserve behavior while proving/developing deferred-open single-owner construction and real session metadata. |
| `app/output/managed_edf_sink.py` (new) | Always allocate predecessor-linked continuation files after errors for the current `pyedflib`; reject same-path reconstruction; close user-stopped recordings so finalization can run while later starts allocate new outputs. |
| `app/output/managed_pvfs_sink.py` (new) | Always allocate predecessor-linked continuation outputs for the current `pvfs_tools`; reject destructive create/writable-reopen paths; enforce user-stop/new-output behavior, nested writer lifecycle, and queue telemetry. |
| `app/output/edf_merger.py`, `app/output/pvfs_merger.py`, control-plane finalization coordinator and dedicated worker (new) | Claim an acquisition-complete logical output, format-read ordered segments, write and verify a temporary merged output, publish once, commit final metadata, retain components for configured recovery, and expose retryable failure/cleanup state without owning hardware. |
| `app/output/influx_sink.py` (new wrapper) | Environment-reference secret resolution and reconstructable redacted config. |
| `app/output/quest_sink.py` (new wrapper) | Reconnect/backoff/delivery-health contract. |
| `app/output/plot_sink.py` or a transport module (new) | Implement the confirmed bounded browser/Vue transport; native Qt display is out of scope. |
| `app/watchdog_process/sink_delivery_outbox.py` (new) | Persist sequenced raw samples separately from telemetry; enforce per-sink age/byte bounds and deployment-wide disk cap; evict oldest with warning/loss evidence; replay/ack after reconnect; recover after watchdog restart without credentials in rows. |
| `app/watchdog_process/outbox.py` | Keep the existing telemetry-only contract; do not add raw samples or repurpose report retention as destination replay. |
| `app/output/managed_file.py`, `app/output/boundaries.py` | Logical sink/segment allocation, versioned boundary evidence, idempotent recovery integration. |
| `app/models/output_file.py`, `app/models/recovery_gap.py` | Represent separate acquisition/artifact states, logical sinks, predecessor-linked physical segments, finalization identity/state, final artifact, component-retention deadline, and typed/versioned recovery boundaries. |
| `app/repositories/recovery_gaps.py` and output repository code | Atomic segment/finalization claims, idempotent boundary and publish commits, fencing, reconciliation lookup, and lookup by runtime/session/device/sink identity. |
| `migrations/versions/*` | Add logical sink/segment and boundary columns/indexes while preserving existing CSV rows. |
| `app/services/sessions.py` | Apply overrides by source nickname plus sink name; ensure error recovery creates/continues the right logical output while stop closes it and schedules finalization before the session is reported fully finalized. |
| `app/services/gaps.py`, `app/services/incidents.py`, health/status services | Distinguish source, individual sink, and presentation failures; aggregate source health without hiding degraded/lost sibling sinks. |
| `app/contracts/*`, event ingest/SSE paths | Carry bounded sink state across watchdog outbox/direct ingest without credentials or high-rate Plot samples. |
| `pyproject.toml`, `requirements.lock`, deployment/doctor config | Define or verify sink extras/native requirements and report availability per sink/platform. |
| editable Morelia `Stream/source.py` and possibly watchdog status code | Stop swallowing sink errors; publish sink-specific status. Changes belong upstream or must be pinned as an explicit backend dependency patch. |
| editable Morelia `plot_sink.py` | Preserve configured `max_display_rate` on reconstruction if native/wrapped PlotSink is used. |
| `tests/` and `tests/hardware/` | Add the full matrix in section 11 and repair/retire the 14 stale baseline failures. |
| architecture/roadmap/runbook docs | Supersede CSV-only statements only after behavior is implemented and proven. |
| Git staging/review policy | `docs/` and `tests/` are now visible; selectively track this specification and the intended acceptance tests without sweeping in unrelated local artifacts. |

## 17. Rollout and compatibility

- Land schema readers before writers: deploy v1+v2 readers while still writing v1, then enable v2
  writes, then retire v1 only after no recoverable v1 runtime remains.
- Keep CSV default behavior unchanged.
- Gate each new sink behind an availability capability reported by daemon/doctor output.
- Do not advertise a sink until its negative recovery proof and target-environment dependency check
  pass.
- Roll back by disabling new sink creation while retaining v2 read/stop/recovery support. Never roll
  back to a binary unable to read already-persisted v2 manifests.
- Mark sessions using an unavailable dependency as blocked with an actionable reason; do not mutate
  their requested sink type.

## 18. Human test-design checkpoint

The user reviewed the proposed decisions on 2026-07-20. Outcomes are labeled per the gap workflow:

| Decision | Recorded answer | Why it matters | Status |
|---|---|---|---|
| What should `plot` mean? | Browser/Vue live plot; no implicit Qt window | Selects a bounded browser data plane and removes Qt ownership ambiguity | `confirmed` |
| How do EDF/PVFS continue after an error? | Continue the same physical output only when proven safe; otherwise create an indexed file such as `B_1.edf` linked to `B.edf`. Current library probes failed, so linked files are mandatory for the inspected versions. | Separates the desired capability from current destructive/corrupting behavior | `confirmed`; experiment `corrected` current strategy |
| What happens to fallback EDF/PVFS files when recording ends? | After all writers close, format-aware merge the ordered linked files into one verified published file; retain components on failure and for a configurable recovery period after success | Adds safe finalization and later recoverable cleanup | `confirmed` / `new_requirement` |
| What happens after a clean user stop? | Mark acquisition complete once writers close; a later or immediate start on the same hardware creates a completely separate output and does not wait for prior merge finalization | Prevents a stopped recording from being resumed or blocking the next run | `confirmed` |
| How are Influx credentials supplied? | Environment-variable reference resolved in watchdog/worker | Prevents durable/log/API secret exposure | `confirmed` |
| What happens when Influx/Quest is unavailable? | Fail initial start. After start warn immediately; buffer raw samples by both time and bytes; drop oldest on overflow; replay retained samples after reconnect; expose permanent loss. | Defines retry, disk, incident, replay, and operator semantics | `confirmed`; requires a new raw `SinkDeliveryOutbox` because the current watchdog telemetry outbox cannot replay samples |
| What is source/sink cardinality? | Source-to-sink is one-to-many; each sink belongs to exactly one source | Requires `sinks[]`, stable IDs, per-sink health, and source-scoped reconstruction of siblings | `corrected` / `new_requirement` |
| Must templates and guided creation support the same sinks? | Yes; session templates carry full sink information and the create quiz can choose/add/edit sinks | Makes the feature reachable and round-trippable through supported operator workflows | `new_requirement` |
| Is this document trackable? | Yes; the docs ignore rule was changed so it is now visible as an untracked file | Makes the review artifact eligible for version control | `confirmed`; file is not staged/committed |
| Are acceptance tests trackable? | Yes; the tests ignore rule was disabled and the directory is visible as untracked content | Required regression and runtime evidence can enter version control after selective review/staging | `confirmed`; tests are not yet tracked |
| Is forced-termination loss acceptable? | Yes, if explicitly reported and all previously durable output is preserved | Avoids an impossible guarantee for samples still resident only in process memory | `accepted_risk` |
| May CI run disposable InfluxDB and QuestDB services? | Yes | Enables real outage/reconnect/replay tests rather than mocks | `confirmed` |
| What hardware evidence is release-blocking? | Exercise the requested sinks on applicable Pod8206HR and Pod8401HR hardware; remote service behavior also runs against disposable services | Keeps file/device construction tied to real POD behavior while allowing service fault injection | `confirmed` |

No material product or operator decision remains open for packet breakdown. Human approval establishes
intent; it does not replace the runtime and hardware proofs listed in section 11.

## 19. Packet-readiness decision

Decision: `ready_for_packetization`.

The critical scenarios, entrypoints, owners, outcomes, acceptance behavior, and verification strategies
are explicit. The user resolved the Plot, secret, remote-outage/replay, stop/restart, component
retention, forced-loss, CI, hardware, template/quiz, cardinality, file-continuation, fallback-merge,
and repository-visibility decisions. Static tracing assigns sink observation to the collection worker,
durable telemetry and command mediation to the watchdog/control-plane ingest boundary, and file
finalization/reconciliation to a control-plane-owned job executed by a dedicated no-hardware worker.

The synthetic experiments established the current implementation direction: neither inspected EDF
nor PVFS path is safe for same-file continuation, while format-aware read-and-rewrite merge is feasible.
The remaining work can change implementation details and release evidence, but no longer changes the
packet boundaries:

- begin with a baseline/repository-hygiene packet that repairs or formally retires the 14 stale failures,
  selectively tracks the specification/tests, and records the exact backend/Morelia diffs;
- retain multi-channel, metadata, crash, writer-process, consumer-tool, and real-hardware EDF/PVFS
  proofs as acceptance gates inside the managed-sink and finalization packets;
- prove the separate delivery outbox against disposable InfluxDB/QuestDB outages, watchdog restart,
  oldest eviction, global disk exhaustion, and replay ordering;
- prove the bounded Vue Plot transport with slow/disconnected browsers;
- do not advertise any sink until its packet-specific negative and runtime gates pass.

`work-packet-breakdown` may now convert the candidate boundaries in section 15 into execution packets.
