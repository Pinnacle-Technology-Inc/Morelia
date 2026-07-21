# Packet 31 — Publish all-sink operational documentation

Status: complete  
Size: M  
Depends on: 30

## Purpose

Update architecture and operator documentation with the implemented contracts, compatibility path, support matrix, observability, recovery, finalization, and rollback guidance.

## Prior state

Existing control-plane documentation is CSV/single-sink oriented, and the design audit is an implementation authority rather than an operator runbook or verified support statement.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Rollout and compatibility” and packet-readiness decision.
- `docs/backend-control-plane-architecture-plan.md` — architecture overview.
- `docs/backend-control-plane-implementation-plan.md` — implementation/rollout description.
- `docs/system-audit-implementation.md` — existing operational audit guidance.
- `docs/watchdog-http-v1.md` — watchdog/status protocol documentation.
- `tests/hardware/README.md` — final hardware gate commands/evidence.
- `docs/sinks/README.md` — packet graph and global invariants.

## Exact edit set

- `docs/backend-control-plane-architecture-plan.md`
- `docs/backend-control-plane-implementation-plan.md`
- `docs/system-audit-implementation.md`
- `docs/sinks/support-matrix.md`
- `docs/sinks/operator-runbook.md`

## Scope boundaries

Do not claim unsupported versions/platforms, copy secrets into examples, or mark a sink production-ready without packet 30 evidence. Preserve the audit as historical design/gap authority.

## Contract / invariant

Documentation matches shipped configuration/API/manifest/state contracts and clearly distinguishes compatibility, preview, experimental, CI-proven, hardware-proven, degraded, lossy, and finalized states.

## Acceptance criteria

1. Support matrix lists every sink's category, dependency, startup policy, recovery policy, buffering/loss policy, finalization behavior, CI/hardware evidence, and known limits.
2. Runbook covers configuration/templates/quiz, credential environment references, preflight failures, sink degradation/loss, EDF/PVFS components/merge, Plot troubleshooting, stop/restart, cleanup, and rollback.
3. Architecture/implementation docs contain no active single-sink/CSV-only contradiction and link to versioned contracts and release evidence.

## Verification

```powershell
rg -n "CSV-only|single sink|sink_type|sink_location|WatchdogOutbox.*raw|PlotSink" docs
.\venv\Scripts\python.exe -m pytest -q tests/test_session_config.py tests/test_runtime_manifest.py tests/test_session_status_api.py
```

Review every search hit as intentional historical/legacy wording or update it.

## Failure handling

If implementation evidence is missing, mark the affected capability pending/experimental and link the blocking packet; do not infer readiness.

## Handoff note

Record the release version/date, completed packet identifiers, evidence links, migration window, rollback owner, and unresolved limitations.

### Packet 31 closeout

- **Release label:** all-sink packets 00A–31 (uncommitted working tree), dated
  2026-07-21.
- **Evidence:** [`support-matrix.md`](support-matrix.md),
  [`IMPLEMENTATION-STATUS.md`](IMPLEMENTATION-STATUS.md), packet 30 gates
  (11 passed) + broad suite note (958/44).
- **Migration window:** v1+v2 readers remain; writers emit v2 `sinks[]`; CSV
  single-sink sessions unchanged; rollback = disable new non-CSV creation while
  retaining v2 read/stop/recovery.
- **Rollback owner:** control-plane on-call (see operator runbook §9).
- **Unresolved limitations:** Plot transport wiring + HTTP token mint;
  `test_device_templates` collection ImportError; 44 pre-existing full-suite
  failures; hardware multi-sink matrix not yet captured.
- Verification: contract tests
  `test_session_config` + `test_runtime_manifest` + `test_session_status_api`
  → **45 passed**. `rg` hits reviewed: remaining `sink_type`/`sink_location`
  wording is compatibility/file-sink/monitor-historical or intentional packet
  prior-state text.
