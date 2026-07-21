# Packet 30 — Add cross-sink release gates

Status: complete  
Size: M  
Depends on: 09A, 22A, 26, 27, 28, 29

## Purpose

Prove the approved multi-sink behavior across unit/integration, disposable service, synthetic file-recovery, and applicable real-hardware gates.

## Prior state

Tests cover CSV and watchdog/source recovery but do not prove all sink combinations, bounded service outages, browser Plot behavior, or EDF/PVFS component integrity end to end.

## Exact read set

- `docs/all-sink-support-design-and-gap-audit.md` — “Test strategy and quality gates”, “Five release-critical scenarios”, and “Human test-design checkpoint”.
- `tests/test_watchdog_process_respawn.py` — crash/restart harness.
- `tests/test_runtime_multi_sink_stack.py` — multi-sink fixtures from packet 26.
- `tests/test_sink_delivery_outbox.py` — service outage controls.
- `tests/hardware/test_crash_recovery.py` — hardware recovery gate.
- `tests/hardware/README.md` — hardware execution instructions.
- `C:/Users/ahoang/vue-dashboard/frontend/src/plot-stream.test.js` — Plot client proof.

## Exact edit set

- `tests/test_multi_sink_runtime.py`
- `tests/test_service_sink_outages.py`
- `tests/hardware/test_crash_recovery.py`
- `tests/hardware/README.md`

## Scope boundaries

Do not fix production defects inside this packet. A failing gate must point back to the owning implementation packet. Disposable Influx/Quest instances are allowed in CI; real hardware gates apply only to Pod8206HR/Pod8401HR environments.

## Contract / invariant

Release evidence covers one source with multiple sinks, sink-isolated failures, EDF/PVFS continuation plus merge, bounded Influx/Quest loss/replay, live Plot lag, and stop/immediate restart identity separation.

## Acceptance criteria

1. Automated tests prove the five release-critical scenarios with exact sample/order/loss/state assertions and no secret leakage.
2. EDF/PVFS experiments assert prior component preservation and exact merged values; service tests assert both time/byte bounds and oldest-drop accounting.
3. Applicable Pod8206HR/Pod8401HR runs record device, sink matrix, failure injection, artifacts, telemetry/status, and pass/fail evidence without making hardware mandatory for ordinary CI.

## Verification

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/test_multi_sink_runtime.py tests/test_service_sink_outages.py
.\venv\Scripts\python.exe -m pytest -q tests/test_real_service_sinks.py
.\venv\Scripts\python.exe -m pytest -q
```

The real-service gate is opt-in: set `PINNACLE_REAL_SINK_INTEGRATION=1`, the four `PINNACLE_TEST_INFLUX_*` variables, and optionally `PINNACLE_TEST_QUEST_HOST` / `PINNACLE_TEST_QUEST_PORT`. It verifies acknowledged writes and destination deduplication against the configured services.

Run the documented hardware command only in the allowed hardware test folder/environment.

## Failure handling

Quarantine nondeterministic external-service/hardware evidence from normal CI, retain artifacts/logs, and file the failure against the owning packet; never weaken data-integrity assertions.

## Handoff note

Record full-suite counts, service versions, hardware evidence, known skips, and support limitations for packet 31.

### Packet 30 closeout (for packet 31)

- Automated gates: `tests/test_multi_sink_runtime.py` +
  `tests/test_service_sink_outages.py` → **11 passed**.
- Full suite (excluding pre-existing collection-broken
  `tests/test_device_templates.py` and opt-in `tests/hardware/`):
  **958 passed, 44 failed** in ~2.5 min. Failures are outside this packet's
  edit set (CLI device-template / config-validate / runtime-cmd / watch /
  host-supervision / multi-device lease) — treat as known pre-existing drift,
  not sink-gate regressions. Packet-30 files are not among the failures.
- Collection blocker: `tests/test_device_templates.py` ImportError
  (`get_by_id` missing from `device_templates`) — quarantine from ordinary CI
  until an owning template packet fixes the import.
- Hardware: `tests/hardware/README.md` documents multi-sink `sink_matrix`
  evidence; `test_multi_sink_matrix_evidence_recorded_when_present` SKIPs
  without matrix (legacy CSV captures) and FAILs when present but incomplete /
  secret-bearing. No Pod8206HR/Pod8401HR run in this closeout.
- Disposable Influx/Quest: not required for the hermetic outage gates (outbox
  bounds/replay/ack). Real service versions: n/a this run.

### 2026-07-21 audit addendum

The live-service test gate now exists in `tests/test_real_service_sinks.py` and cannot pass through fake clients. The local Docker client was present during this audit, but no Docker engine was running, so the gate was collected and skipped rather than falsely reported as executed. Run it against the InfluxDB/QuestDB deployment under `C:/Users/ahoang/Morelia` before release.

The ordinary backend suite, excluding only the known collection-broken `tests/test_device_templates.py` and opt-in `tests/hardware/`, produced **972 passed, 44 failed, 2 skipped**. The same 44 previously recorded device-template/CLI/runtime-host/legacy-manifest failures remain; no focused sink/finalizer/Morelia gate failed.
- Support limitations for the matrix: live Plot still needs
  `plot_transport` wiring + HTTP token mint (integrator follow-ups from 27/28);
  PVFS merge remains Windows-rename-constrained (packet 18 note).
