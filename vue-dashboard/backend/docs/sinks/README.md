# All-sink support work packets

Authority: [`../all-sink-support-design-and-gap-audit.md`](../all-sink-support-design-and-gap-audit.md).

These packets convert the approved design and gap audit into independently verifiable implementation units. Execute them in dependency order. A packet is complete only when its acceptance criteria and verification commands pass and its handoff note has been recorded.

## Global invariants

- One source owns an ordered, non-empty `sinks[]`; each sink belongs to exactly one source. Repeated sink types are allowed when `sink_name` is unique within the source.
- New writers emit only the nested multi-sink contract. Readers accept the documented legacy flattened contract and normalize it immediately.
- File sinks are CSV, EDF, and PVFS. Service sinks are Influx and Quest. Plot is a bounded browser/Vue live-view path, not a file sink.
- Only a runtime worker may own live sink handles or resolve Influx credentials. Tokens never enter configuration, manifests, logs, reports, templates, or status responses.
- EDF/PVFS recovery creates linked continuation components. User stop completes the acquisition; a later start creates a new acquisition and new output identity.
- `SinkDeliveryOutbox` carries raw service-sink delivery data only. `WatchdogOutbox` remains telemetry-only.
- Source health and per-sink health are separate. A sink failure must not masquerade as source recovery.
- Every lossy transition is explicit, bounded, observable, and attributable to a sink and acquisition.

## Packet index

| Packet | Size | Depends on | Outcome |
|---|---:|---|---|
| [00A](00a-repository-provenance.md) | XS | — | Capture dirty-worktree and dependency provenance |
| [00](00-baseline-fixtures.md) | S | 00A | Restore a trustworthy targeted baseline |
| [01](01-sink-registry.md) | M | 00 | Register and validate all six sink types |
| [02](02-session-multi-sink-config.md) | M | 01 | Canonical multi-sink session configuration |
| [03](03-template-sink-round-trip.md) | M | 02 | Template import/export preserves sinks |
| [04](04-api-multi-sink-contract.md) | M | 02, 03 | API accepts and returns `sinks[]` |
| [05](05-cli-sink-quiz.md) | M | 03, 04 | Guided create/template flows choose sinks |
| [06](06-runtime-manifest-v2-model.md) | M | 00, 01 | Versioned multi-sink manifest wire model |
| [07](07-runtime-manifest-resolution.md) | M | 02, 06 | Resolve canonical config into manifest v2 |
| [08](08-optional-sink-dependencies.md) | S | 00 | Declare and test sink dependency groups |
| [09](09-sink-aware-startup-preflight.md) | M | 07, 08 | Validate only selected sink dependencies/services |
| [09A](09a-sink-doctor.md) | S | 01, 08 | Report per-sink installation/readiness diagnostics |
| [10](10-output-lifecycle-schema.md) | M | 00 | Persist acquisitions, components, delivery, and finalization state |
| [11](11-segment-allocation-and-boundaries.md) | M | 10 | Allocate monotonic linked components safely |
| [12](12-csv-worker-ownership.md) | M | 07, 11 | Enforce worker-only CSV handle ownership |
| [13](13-runtime-sink-factory.md) | S | 07, 08, 12 | Centralize runtime sink construction |
| [14](14-managed-edf-sink.md) | S | 11, 13 | Write EDF continuation components safely |
| [15](15-managed-pvfs-sink.md) | S | 11, 13 | Write PVFS continuation components safely |
| [16](16-finalization-coordinator.md) | M | 10, 11 | Run durable, fenced finalization jobs |
| [17](17-edf-component-merger.md) | S | 14, 16 | Merge EDF components after acquisition completion |
| [18](18-pvfs-component-merger.md) | S | 15, 16 | Merge PVFS components after acquisition completion |
| [19](19-sink-delivery-outbox.md) | M | 08, 10 | Bound and replay service-sink data independently of telemetry |
| [20](20-sink-report-wire-contract.md) | M | 06 | Carry bounded per-sink state across process boundaries |
| [21](21-sink-state-ingest.md) | M | 10, 20 | Persist sink incidents, loss, and recovery state |
| [22](22-sink-status-api.md) | S | 04, 21 | Expose source and sink state separately |
| [22A](22a-cli-sink-status.md) | S | 05, 22 | Render source, sink, and transport state in CLI output |
| [23](23-morelia-sink-error-callback.md) | M | 00 | Replace printed sink failures with structured callbacks |
| [24](24-influx-runtime-adapter.md) | S | 13, 19, 23 | Resolve credentials and deliver/replay Influx writes |
| [25](25-quest-runtime-adapter.md) | S | 13, 19, 23 | Deliver/replay Quest writes |
| [26](26-runtime-multi-sink-integration.md) | M | 14, 15, 20, 23, 24, 25 | Construct and supervise all selected sinks |
| [27](27-backend-plot-transport.md) | M | 13, 20, 26 | Publish bounded authenticated live plot samples |
| [28](28-vue-live-plot.md) | M | 22, 27 | Render live Plot data in the Vue UI |
| [29](29-stop-and-restart-finalization.md) | M | 16, 17, 18, 19, 21, 26 | Separate completed acquisitions from later starts |
| [30](30-cross-sink-release-gates.md) | M | 09A, 22A, 26, 27, 28, 29 | Prove failure isolation and recovery across sinks |
| [31](31-rollout-documentation.md) | M | 30 | Publish support matrix, operations, and rollout guidance |

## Suggested execution lanes

1. Foundation: 00–11, including 09A.
2. File sinks and finalization: 12–18.
3. Service delivery and observability: 19–26, including 22A.
4. Plot: 27–28.
5. Lifecycle integration and release: 29–31.

Packets in the same lane may run in parallel only when their declared dependencies are already complete and their exact edit sets do not overlap. `23-morelia-sink-error-callback.md` changes the separate Morelia checkout and must preserve its existing dirty worktree.

## Gap coverage

| Audit gaps | Owning packets |
|---|---|
| SINK-01, SINK-17 | 01 |
| SINK-02, SINK-25 | 02–05 |
| SINK-03, SINK-11, SINK-20 | 06, 07, 10, 30 |
| SINK-04 | 13, 26 |
| SINK-05 | 14, 17, 30 |
| SINK-06 | 15, 18, 30 |
| SINK-07 | 01, 02, 09, 24 |
| SINK-08, SINK-23 | 20–26 |
| SINK-09, SINK-10 | 27, 28 |
| SINK-12, SINK-18, SINK-24 | 10, 11, 21, 29 |
| SINK-13 | 08, 09, 09A |
| SINK-14, SINK-15 | 00, 30 |
| SINK-16 | 00A, 23, 31 |
| SINK-19 | 20, 23, 26 |
| SINK-21 | 12, 13 |
| SINK-22 | 02–07, 13, 26 |
| SINK-26 | 16–18, 29, 30 |
| SINK-27 | 19, 24–26 |

## Completion record

For every completed packet, record the commit or change identifier, verification result, any accepted deviation, and the next packet's relevant handoff facts in that packet or the implementation tracker. Do not silently weaken an invariant to make a test pass.
